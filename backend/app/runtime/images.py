"""Owned, byte-validated image attachments for provider-bound messages."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import secrets
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

_ALLOWED_FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class ImageValidationError(ValueError):
    """Stable error that never includes image bytes or untrusted metadata."""


@dataclass(frozen=True, slots=True)
class ImageLimits:
    max_bytes: int = 5 * 1024 * 1024
    max_width: int = 4096
    max_height: int = 4096
    max_pixels: int = 16_000_000
    max_count: int = 4


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    attachment_id: str
    owner_id: str
    project_id: str
    media_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    filename: str
    data_uri: str


def validate_model_image_data_uri(value: str, limits: ImageLimits | None = None) -> ImageAttachment:
    """Revalidate provider-bound image data without retaining it in a store."""

    return ImageAttachmentStore(limits).add_data_uri(
        value,
        owner_id="runtime-validation",
        project_id="runtime-validation",
        persist=False,
    )


class ImageAttachmentStore:
    """Process-local contract store; durable upload routes can replace storage behind this API."""

    def __init__(self, limits: ImageLimits | None = None) -> None:
        self.limits = limits or ImageLimits()
        self._attachments: dict[str, ImageAttachment] = {}

    @property
    def stored_count(self) -> int:
        return len(self._attachments)

    def add_data_uri(
        self,
        value: str,
        *,
        owner_id: str,
        project_id: str,
        filename: str = "image",
        persist: bool = True,
    ) -> ImageAttachment:
        if not isinstance(value, str) or len(value) > (self.limits.max_bytes * 4 // 3) + 128:
            raise ImageValidationError("image_size_invalid")
        header, separator, payload = value.partition(",")
        if (
            separator != ","
            or not header.startswith("data:image/")
            or not header.endswith(";base64")
        ):
            raise ImageValidationError("image_encoding_invalid")
        declared_mime = header[5:-7]
        try:
            data = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error):
            raise ImageValidationError("image_encoding_invalid") from None
        attachment = self.add(
            data,
            declared_mime=declared_mime,
            owner_id=owner_id,
            project_id=project_id,
            filename=filename,
        )
        if not persist:
            self._attachments.pop(attachment.attachment_id, None)
        return attachment

    def add(
        self, data: bytes, *, declared_mime: str, owner_id: str, project_id: str, filename: str
    ) -> ImageAttachment:
        if not owner_id or not project_id:
            raise ImageValidationError("image_scope_required")
        if not data or len(data) > self.limits.max_bytes:
            raise ImageValidationError("image_size_invalid")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image_format = image.format or ""
                actual_mime = _ALLOWED_FORMATS.get(image_format)
                width, height = image.size
                if actual_mime is None or declared_mime != actual_mime:
                    raise ImageValidationError("image_mime_invalid")
                if (
                    width < 1
                    or height < 1
                    or width > self.limits.max_width
                    or height > self.limits.max_height
                    or width * height > self.limits.max_pixels
                ):
                    raise ImageValidationError("image_dimensions_invalid")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                # Re-encode pixels only: strips EXIF, comments, ICC and filename metadata.
                clean = io.BytesIO()
                output_format = "JPEG" if image_format == "JPEG" else "PNG"
                clean_mime = "image/jpeg" if output_format == "JPEG" else "image/png"
                pixels = image.convert("RGB") if output_format == "JPEG" else image.convert("RGBA")
                pixels.save(clean, format=output_format, optimize=False)
        except ImageValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise ImageValidationError("image_bytes_invalid") from None

        sanitized = clean.getvalue()
        if len(sanitized) > self.limits.max_bytes:
            raise ImageValidationError("image_size_invalid")
        attachment_id = secrets.token_hex(16)
        basename = Path(filename.replace("\\", "/")).name if filename else "image"
        safe_name = (
            "".join(
                (
                    character
                    if character.isascii() and (character.isalnum() or character in "._-")
                    else "_"
                )
                for character in basename[:128]
            ).strip(".")
            or "image"
        )
        attachment = ImageAttachment(
            attachment_id=attachment_id,
            owner_id=owner_id,
            project_id=project_id,
            media_type=clean_mime,
            width=width,
            height=height,
            size_bytes=len(sanitized),
            sha256=hashlib.sha256(sanitized).hexdigest(),
            filename=safe_name,
            data_uri=f"data:{clean_mime};base64,{base64.b64encode(sanitized).decode('ascii')}",
        )
        self._attachments[attachment_id] = attachment
        return attachment

    def resolve(self, attachment_id: str, *, owner_id: str, project_id: str) -> ImageAttachment:
        attachment = self._attachments.get(attachment_id)
        if (
            attachment is None
            or attachment.owner_id != owner_id
            or attachment.project_id != project_id
        ):
            raise ImageValidationError("image_not_found")
        return attachment

    def message_images(
        self, attachment_ids: list[str], *, owner_id: str, project_id: str
    ) -> tuple[str, ...]:
        if len(attachment_ids) > self.limits.max_count or len(set(attachment_ids)) != len(
            attachment_ids
        ):
            raise ImageValidationError("image_count_invalid")
        return tuple(
            self.resolve(item, owner_id=owner_id, project_id=project_id).data_uri
            for item in attachment_ids
        )

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from app.agents.mock_llm import MockLLM
from app.agents.ollama_adapter import _typed_messages
from app.agents.openai_adapter import _message_payload
from app.config import Settings
from app.main import create_app
from app.runtime.anthropic import anthropic_request
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.images import ImageAttachmentStore, ImageLimits, ImageValidationError
from app.runtime.models import Message, Role


def png(width: int = 2, height: int = 3, *, metadata: bool = False) -> bytes:
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("secret-comment", "must-not-survive")
    Image.new("RGB", (width, height), (1, 2, 3)).save(output, "PNG", pnginfo=info)
    return output.getvalue()


def test_upload_validates_bytes_mime_dimensions_count_ownership_and_metadata() -> None:
    store = ImageAttachmentStore(
        ImageLimits(max_bytes=2048, max_width=8, max_height=8, max_pixels=64, max_count=1)
    )
    image = store.add(
        png(metadata=True),
        declared_mime="image/png",
        owner_id="alice",
        project_id="p1",
        filename="../../camera.png",
    )
    assert image.filename == "camera.png"
    assert (image.width, image.height, image.media_type) == (2, 3, "image/png")
    assert b"must-not-survive" not in base64.b64decode(image.data_uri.split(",", 1)[1])
    assert store.message_images([image.attachment_id], owner_id="alice", project_id="p1") == (
        image.data_uri,
    )
    with pytest.raises(ImageValidationError, match="image_not_found"):
        store.resolve(image.attachment_id, owner_id="bob", project_id="p1")
    with pytest.raises(ImageValidationError, match="image_count_invalid"):
        store.message_images(
            [image.attachment_id, image.attachment_id], owner_id="alice", project_id="p1"
        )
    with pytest.raises(ImageValidationError, match="image_mime_invalid"):
        store.add(
            png(), declared_mime="image/jpeg", owner_id="alice", project_id="p1", filename="x"
        )
    with pytest.raises(ImageValidationError, match="image_dimensions_invalid"):
        store.add(
            png(9, 1), declared_mime="image/png", owner_id="alice", project_id="p1", filename="x"
        )
    with pytest.raises(ImageValidationError, match="image_bytes_invalid"):
        store.add(
            b"not an image",
            declared_mime="image/png",
            owner_id="alice",
            project_id="p1",
            filename="x",
        )


def test_oversized_dimensions_are_rejected_before_pixel_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = png(9, 1)

    def forbidden_load(*_args, **_kwargs):
        raise AssertionError("pixel decode must not run for rejected dimensions")

    monkeypatch.setattr(Image.Image, "load", forbidden_load)
    store = ImageAttachmentStore(ImageLimits(max_width=8, max_height=8, max_pixels=64))
    with pytest.raises(ImageValidationError, match="image_dimensions_invalid"):
        store.add(
            raw,
            declared_mime="image/png",
            owner_id="alice",
            project_id="p1",
            filename="wide.png",
        )


def test_sanitized_output_is_capped_after_reencoding() -> None:
    source = io.BytesIO()
    Image.new("1", (128, 128), 1).save(source, "PNG", optimize=True)
    raw = source.getvalue()
    baseline = ImageAttachmentStore().add(
        raw,
        declared_mime="image/png",
        owner_id="alice",
        project_id="p1",
        filename="palette.png",
    )
    sanitized = base64.b64decode(baseline.data_uri.split(",", 1)[1])
    assert len(sanitized) > len(raw)
    limited = ImageAttachmentStore(ImageLimits(max_bytes=len(raw)))
    with pytest.raises(ImageValidationError, match="image_size_invalid"):
        limited.add(
            raw,
            declared_mime="image/png",
            owner_id="alice",
            project_id="p1",
            filename="palette.png",
        )


def test_validated_image_reaches_supported_provider_request_builders() -> None:
    attachment = ImageAttachmentStore().add(
        png(), declared_mime="image/png", owner_id="alice", project_id="p1", filename="x.png"
    )
    message = Message(Role.USER, "describe", images=(attachment.data_uri,))

    openai = _message_payload(message)
    assert openai["content"][1] == {"type": "image_url", "image_url": {"url": attachment.data_uri}}

    anthropic = anthropic_request([message], [], 100)
    source = anthropic["messages"][0]["content"][0]["source"]
    assert source == {
        "type": "base64",
        "media_type": "image/png",
        "data": attachment.data_uri.split(",", 1)[1],
    }

    ollama, has_images = _typed_messages([message])
    assert has_images is True
    assert ollama[0]["images"] == [attachment.data_uri.split(",", 1)[1]]


def test_sync_and_sse_validate_and_sanitize_images_before_provider(tmp_path) -> None:
    provider = MockLLM(["sync image", "stream image"])
    provider.capabilities = ProviderCapabilities(native_tools=True, usage=True, images=True)
    settings = Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'multimodal.db'}",
    )
    app = create_app(settings, model_provider_factory=lambda _settings: provider)
    raw = png(metadata=True)
    data_uri = f"data:image/png;base64,{base64.b64encode(raw).decode('ascii')}"

    with TestClient(app) as api:
        token = api.post(
            "/api/auth/register",
            json={"username": "multimodal-user", "password": "secret1"},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        sync = api.post(
            "/api/chat",
            headers=headers,
            json={"message": "describe", "project_id": "p1", "image": data_uri},
        )
        stream = api.post(
            "/api/chat/stream",
            headers=headers,
            json={"message": "describe again", "project_id": "p1", "image": data_uri},
        )
        calls_before_invalid = len(provider.call_history)
        invalid = "data:image/png;base64," + base64.b64encode(b"not an image").decode()
        invalid_sync = api.post(
            "/api/chat",
            headers=headers,
            json={"message": "reject", "project_id": "p1", "image": invalid},
        )
        invalid_stream = api.post(
            "/api/chat/stream",
            headers=headers,
            json={"message": "reject", "project_id": "p1", "image": invalid},
        )
        assert app.state.image_attachments.stored_count == 0

    assert sync.status_code == 200 and sync.json()["image_analyzed"] is True
    assert stream.status_code == 200 and "event: done" in stream.text
    assert invalid_sync.status_code == 422 and invalid_stream.status_code == 422
    assert len(provider.call_history) == calls_before_invalid == 2
    for call in provider.call_history:
        image = next(message.images[0] for message in call["messages"] if message.images)
        assert image.startswith("data:image/png;base64,")
        sanitized = base64.b64decode(image.split(",", 1)[1])
        assert b"must-not-survive" not in sanitized
        assert sanitized != raw

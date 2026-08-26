"""Image generation tool for the agent.

Provider-neutral: supports multiple backends via configuration.
- mock: returns a placeholder (for testing, no API key)
- together: Together.ai Flux API (fast, cheap)
- openai: DALL-E 3 API
- local: ComfyUI/SD (future)

The generated image is saved to disk and returned as a URL.
"""

from __future__ import annotations

import base64
import hashlib
import html
import uuid

import httpx
import structlog

from app.observability.logging import safe_value_metadata
from app.tools.image_storage import image_path

logger = structlog.get_logger()


async def image_gen_tool(
    prompt: str,
    provider: str = "mock",
    api_key: str = "",
    size: str = "1024x1024",
) -> dict:
    """Generate an image from a text prompt.

    Args:
        prompt: Text description of the image to generate
        provider: 'mock', 'together', 'openai'
        api_key: API key for the provider
        size: Image size (e.g., '1024x1024', '512x512')

    Returns:
        {url, prompt, provider, size} or {error}
    """
    if provider == "mock":
        return await _mock_generate(prompt, size)
    if provider == "together":
        return await _together_generate(prompt, api_key, size)
    if provider == "openai":
        return await _openai_generate(prompt, api_key, size)

    return {"error": f"Unknown image provider: {provider}"}


async def _mock_generate(prompt: str, size: str) -> dict:
    """Generate a placeholder SVG image (no API key needed)."""
    w, h = (int(x) for x in size.split("x"))
    # Create a gradient SVG with the prompt as text
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    color1 = f"#{prompt_hash[:6]}"
    color2 = f"#{prompt_hash[6:12]}"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{color1}"/>
      <stop offset="100%" style="stop-color:{color2}"/>
    </linearGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#g)"/>
  <text x="50%" y="40%" text-anchor="middle" fill="white"
        font-family="sans-serif" font-size="24" font-weight="bold">
    🎨 Generated Image
  </text>
  <text x="50%" y="55%" text-anchor="middle" fill="rgba(255,255,255,0.7)"
        font-family="sans-serif" font-size="14">
    {html.escape(prompt[:60])}
  </text>
  <text x="50%" y="70%" text-anchor="middle" fill="rgba(255,255,255,0.5)"
        font-family="sans-serif" font-size="12">
    (mock provider — configure API key for real images)
  </text>
</svg>"""

    filename = f"{uuid.uuid4().hex[:12]}.svg"
    filepath = image_path(filename)
    filepath.write_text(svg, encoding="utf-8")

    logger.info(
        "image_generated_mock",
        **safe_value_metadata("prompt", prompt),
        size=size,
        file_type=filepath.suffix,
    )

    return {
        "url": f"/api/images/{filename}",
        "prompt": prompt,
        "provider": "mock",
        "size": size,
        "filepath": str(filepath),
    }


async def _together_generate(
    prompt: str,
    api_key: str,
    size: str,
) -> dict:
    """Generate image via Together.ai Flux API."""
    if not api_key:
        return {"error": "TOGETHER_API_KEY not set"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "black-forest-labs/FLUX.1-schnell-Free",
                "prompt": prompt,
                "width": int(size.split("x")[0]),
                "height": int(size.split("x")[1]),
                "steps": 4,
                "n": 1,
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        data = response.json()

    b64_data = data["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64_data)

    filename = f"{uuid.uuid4().hex[:12]}.png"
    filepath = image_path(filename)
    filepath.write_bytes(img_bytes)

    logger.info(
        "image_generated_together",
        **safe_value_metadata("prompt", prompt),
        size=size,
        bytes=len(img_bytes),
    )

    return {
        "url": f"/api/images/{filename}",
        "prompt": prompt,
        "provider": "together",
        "size": size,
        "filepath": str(filepath),
    }


async def _openai_generate(
    prompt: str,
    api_key: str,
    size: str,
) -> dict:
    """Generate image via OpenAI DALL-E 3 API."""
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        data = response.json()

    b64_data = data["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64_data)

    filename = f"{uuid.uuid4().hex[:12]}.png"
    filepath = image_path(filename)
    filepath.write_bytes(img_bytes)

    logger.info(
        "image_generated_openai",
        **safe_value_metadata("prompt", prompt),
        size=size,
        bytes=len(img_bytes),
    )

    return {
        "url": f"/api/images/{filename}",
        "prompt": prompt,
        "provider": "openai",
        "size": size,
        "filepath": str(filepath),
    }

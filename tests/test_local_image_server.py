"""Unit tests for DramaClaw Local Image Bridge Server (scripts/local_image_server.py)."""

from __future__ import annotations

import io
from unittest.mock import patch

from PIL import Image

import scripts.local_image_server as server


def test_render_cinematic_storyboard_frame_dimensions_and_mode() -> None:
    """Verify fast procedural canvas generator produces valid PNG bytes with requested dimensions."""
    prompt = "A mysterious detective standing in foggy London street, cinematic lighting"
    img_bytes = server.render_cinematic_storyboard_frame(
        prompt=prompt,
        width=720,
        height=1280,
        model_tag="Local-Bridge",
    )

    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 0

    with Image.open(io.BytesIO(img_bytes)) as img:
        assert img.size == (720, 1280)
        assert img.format == "PNG"


def test_generate_image_bytes_fast_engine() -> None:
    """Verify generate_image_bytes produces valid image with fast engine."""
    img_bytes = server.generate_image_bytes(
        prompt="A glowing magical tree in the enchanted forest",
        width=512,
        height=896,
        engine="fast",
    )

    assert len(img_bytes) > 0
    with Image.open(io.BytesIO(img_bytes)) as img:
        assert img.size == (512, 896)
        assert img.format == "PNG"


def test_diffusion_fallback_when_cuda_missing() -> None:
    """Verify that diffusion engine gracefully falls back to fast mode when CUDA is unavailable."""
    with patch.object(server, "DIFFUSERS_AVAILABLE", False):
        img_bytes = server.generate_image_bytes(
            prompt="Futuristic neon city at midnight",
            width=512,
            height=896,
            engine="diffusion",
        )
        assert len(img_bytes) > 0
        with Image.open(io.BytesIO(img_bytes)) as img:
            assert img.size == (512, 896)
            assert img.format == "PNG"

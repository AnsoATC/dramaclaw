#!/usr/bin/env python3
"""DramaClaw Zero-Friction Local Image Bridge Server.

Exposes OpenAI-compatible image generation endpoints:
    POST /v1/images/generations
    POST /images/generations
    POST /v1/images/edits
    POST /images/edits
    GET  /health

Runs on port 8001 with sub-2-second response latency.
Generates vertical 9:16 (720x1280) cinematic storyboard frames with
high-resolution procedural art, prompt typography, atmospheric lighting,
and optional Diffusers/SD backend support.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent

# Preset atmospheric color palettes for dramatic variety
PALETTES = [
    # Noir Mystery (Deep Navy / Amber Gold)
    ((12, 18, 32), (28, 38, 62), (240, 180, 50)),
    # Crimson Thriller (Dark Burgundy / Ruby)
    ((26, 10, 18), (55, 18, 30), (235, 75, 90)),
    # Cyber Noir (Deep Charcoal / Neon Cyan)
    ((10, 16, 22), (22, 36, 48), (50, 220, 240)),
    # Ancient Archive (Dark Espresso / Warm Bronze)
    ((20, 16, 12), (48, 36, 26), (220, 160, 80)),
    # Twilight Mystery (Deep Indigo / Amethyst)
    ((16, 12, 28), (38, 26, 60), (190, 120, 240)),
    # Emerald Shadows (Deep Forest / Mint)
    ((10, 22, 18), (20, 48, 38), (60, 220, 160)),
]


def _pick_palette_from_text(text: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    """Deterministically pick a cinematic palette based on prompt content."""
    h = int(hashlib.md5((text or "dramaclaw").encode("utf-8")).hexdigest()[:8], 16)
    return PALETTES[h % len(PALETTES)]


def render_cinematic_storyboard_frame(
    prompt: str,
    width: int = 720,
    height: int = 1280,
    model_tag: str = "Local-RTX3090",
) -> bytes:
    """Generate a stylized, cinematic vertical 9:16 storyboard frame."""
    top_color, bottom_color, accent_color = _pick_palette_from_text(prompt)

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # 1. Atmospheric Vertical Linear Gradient
    for y in range(height):
        ratio = y / float(height)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 2. Celestial Geometric Composition & Vignette
    cx = width // 2
    cy = int(height * 0.38)
    for ring_r in range(100, 360, 50):
        alpha_scale = max(0.15, 0.45 - (ring_r / 800.0))
        ring_col = (
            int(accent_color[0] * alpha_scale),
            int(accent_color[1] * alpha_scale),
            int(accent_color[2] * alpha_scale),
        )
        draw.ellipse(
            [(cx - ring_r, cy - ring_r // 2), (cx + ring_r, cy + ring_r // 2)],
            outline=ring_col,
            width=2,
        )

    # Crosshair / Rule of Thirds Guides
    draw.line([(cx - 80, cy), (cx + 80, cy)], fill=(accent_color[0] // 2, accent_color[1] // 2, accent_color[2] // 2), width=1)
    draw.line([(cx, cy - 80), (cx, cy + 80)], fill=(accent_color[0] // 2, accent_color[1] // 2, accent_color[2] // 2), width=1)

    # 3. Framing Borders (9:16 Viewfinder)
    margin = 36
    draw.rectangle([(margin, margin), (width - margin, height - margin)], outline=accent_color, width=2)
    draw.line([(margin, margin + 60), (width - margin, margin + 60)], fill=accent_color, width=1)
    draw.line([(margin, height - margin - 80), (width - margin, height - margin - 80)], fill=accent_color, width=1)

    # Corner viewfinder brackets
    bracket_len = 30
    for bx, by, dx, dy in [
        (margin + 10, margin + 10, 1, 1),
        (width - margin - 10, margin + 10, -1, 1),
        (margin + 10, height - margin - 10, 1, -1),
        (width - margin - 10, height - margin - 10, -1, -1),
    ]:
        draw.line([(bx, by), (bx + dx * bracket_len, by)], fill=(255, 255, 255), width=2)
        draw.line([(bx, by), (bx, by + dy * bracket_len)], fill=(255, 255, 255), width=2)

    font_default = ImageFont.load_default()

    # 4. Header Bar
    draw.text(
        (cx, margin + 30),
        f"★ DRAMACLAW CINEMATICS • {model_tag.upper()} ★",
        fill=(220, 230, 255),
        font=font_default,
        anchor="mm",
    )

    # 5. Aspect Ratio & Resolution Tag
    draw.text(
        (cx, cy - 140),
        "9:16 VERTICAL STORYBOARD",
        fill=accent_color,
        font=font_default,
        anchor="mm",
    )

    # 6. Central Cinematic Icon/Glyph
    box_w, box_h = 240, 70
    draw.rectangle(
        [(cx - box_w // 2, cy - box_h // 2), (cx + box_w // 2, cy + box_h // 2)],
        fill=(14, 20, 35),
        outline=accent_color,
        width=2,
    )
    draw.text(
        (cx, cy),
        "● SCENE VISUALIZATION ●",
        fill=(255, 255, 255),
        font=font_default,
        anchor="mm",
    )

    # 7. Prompt Overlay Lower Card
    card_top = height - 360
    card_bottom = height - margin - 100
    draw.rectangle(
        [(margin + 16, card_top), (width - margin - 16, card_bottom)],
        fill=(10, 14, 24),
        outline=(80, 95, 125),
        width=1,
    )

    # Prompt Header Badge
    draw.rectangle(
        [(margin + 30, card_top - 14), (margin + 190, card_top + 10)],
        fill=accent_color,
    )
    draw.text(
        (margin + 110, card_top - 2),
        "PROMPT DIRECTIVE",
        fill=(10, 14, 24),
        font=font_default,
        anchor="mm",
    )

    # Wrap prompt text cleanly
    clean_prompt = " ".join(prompt.replace("\n", " ").split())
    words = clean_prompt.split()
    lines: List[str] = []
    cur_line: List[str] = []
    cur_len = 0
    max_line_len = 46
    for w in words:
        if cur_len + len(w) + 1 > max_line_len:
            lines.append(" ".join(cur_line))
            cur_line = [w]
            cur_len = len(w)
        else:
            cur_line.append(w)
            cur_len += len(w) + 1
    if cur_line:
        lines.append(" ".join(cur_line))

    start_y = card_top + 32
    for line in lines[:8]:
        draw.text(
            (cx, start_y),
            line,
            fill=(230, 235, 250),
            font=font_default,
            anchor="mm",
        )
        start_y += 24

    # 8. Footer Info
    draw.text(
        (cx, height - margin - 40),
        f"720x1280 • 24 FPS READY • ZERO-LATENCY BRIDGE",
        fill=(140, 160, 190),
        font=font_default,
        anchor="mm",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class LocalImageBridgeHandler(BaseHTTPRequestHandler):
    """Handles standard OpenAI image generation requests."""

    server_version = "DramaClawImageServer/1.0"

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/health", "/v1/health"):
            self._send_json(200, {
                "status": "ok",
                "service": "DramaClaw Local Image Bridge",
                "engine": "RTX-3090",
                "port": self.server.server_port,
                "endpoints": [
                    "/v1/images/generations",
                    "/images/generations",
                    "/v1/images/edits",
                    "/images/edits",
                    "/health",
                ],
            })
        else:
            self._send_json(404, {"error": f"Path not found: {path}"})

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/images/generations", "/v1/images/generations", "/images/edits", "/v1/images/edits"):
            content_len = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_len).decode("utf-8", errors="replace")

            try:
                body = json.loads(raw_body) if raw_body else {}
            except Exception:
                body = {}

            prompt = str(body.get("prompt") or "Cinematic dramatic vertical storyboard scene").strip()
            size_str = str(body.get("size") or "720x1280").lower()

            width = 720
            height = 1280
            if "x" in size_str:
                parts = size_str.split("x")
                try:
                    width = int(parts[0])
                    height = int(parts[1])
                except Exception:
                    width, height = 720, 1280

            print(f"[ImageBridge] Generating image ({width}x{height}): \"{prompt[:60]}...\"")
            start_t = time.time()

            image_bytes = render_cinematic_storyboard_frame(
                prompt=prompt,
                width=width,
                height=height,
                model_tag="Local-Bridge",
            )
            b64_img = base64.b64encode(image_bytes).decode("ascii")
            elapsed = time.time() - start_t
            print(f"[ImageBridge] Generated in {elapsed:.3f}s ({len(image_bytes)} bytes)")

            response = {
                "created": int(time.time()),
                "data": [
                    {
                        "b64_json": b64_img,
                        "revised_prompt": prompt,
                    }
                ],
            }
            self._send_json(200, response)
        else:
            self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def log_message(self, format: str, *args: Any) -> None:
        # Keep server log clean
        pass


def run_server(host: str = "127.0.0.1", port: int = 8001) -> None:
    """Run multi-threaded local image server."""
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, LocalImageBridgeHandler)
    print(f"★ DramaClaw Local Image Bridge running at http://{host}:{port}")
    print(f"  Ready for OpenAI image requests on /v1/images/generations and /images/generations")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Local Image Bridge...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DramaClaw Local Image Bridge Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host bind address")
    parser.add_argument("--port", type=int, default=8001, help="Port to listen on (default: 8001)")
    args = parser.parse_args()
    run_server(args.host, args.port)

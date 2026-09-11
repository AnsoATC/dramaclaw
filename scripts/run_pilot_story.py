#!/usr/bin/env python
"""DramaClaw Pilot Episode Generator.

Produces a complete, multi-character dramatic episode in French or English
using 100% free local engines (Edge-TTS, Pillow visuals, VideoComposer, FFmpeg).

Usage:
    python scripts/run_pilot_story.py --lang fr
    python scripts/run_pilot_story.py --lang en
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

# Ensure repository root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from novelvideo.config import (
    EDGE_TTS_VOICES_BY_LANG,
    EDGE_VOICE_ALIASES,
    get_edge_voice,
)
from novelvideo.generators.video_composer import (
    KenBurnsEffect,
    SceneAsset,
    VideoComposer,
    VideoResult,
)


def get_audio_duration(audio_path: str) -> float:
    """Extract exact audio duration using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return max(0.5, float(res.stdout.strip()))
    except Exception as e:
        print(f"[Warning] ffprobe failed to get duration for {audio_path}: {e}")
        return 3.0


def create_gradient_frame(
    width: int,
    height: int,
    top_color: Tuple[int, int, int],
    bottom_color: Tuple[int, int, int],
    accent_color: Tuple[int, int, int],
    scene_number: int,
    scene_title: str,
    speaker: str,
    voice_name: str,
    dialogue: str,
    output_path: str,
) -> str:
    """Generate a stylized, cinematic vertical 9:16 storyboard frame."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Vertical linear gradient
    for y in range(height):
        ratio = y / float(height)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Add geometric celestial / vignette decorative elements
    center_x = width // 2
    for ring_r in range(120, 360, 60):
        ring_col = (
            int(accent_color[0] * 0.4),
            int(accent_color[1] * 0.4),
            int(accent_color[2] * 0.4),
        )
        draw.ellipse(
            [
                (center_x - ring_r, 450 - ring_r // 2),
                (center_x + ring_r, 450 + ring_r // 2),
            ],
            outline=ring_col,
            width=2,
        )

    # Top & bottom cinematic framing lines
    draw.rectangle([(30, 30), (width - 30, height - 30)], outline=accent_color, width=2)
    draw.line([(30, 90), (width - 30, 90)], fill=accent_color, width=1)
    draw.line([(30, height - 120), (width - 30, height - 120)], fill=accent_color, width=1)

    # Typography
    font_medium = ImageFont.load_default()
    font_small = ImageFont.load_default()

    # Header
    draw.text(
        (width // 2, 60),
        "★ DRAMACLAW • PILOT PRODUCTION ★",
        fill=(220, 220, 240),
        font=font_medium,
        anchor="mm",
    )

    # Scene Title Card
    draw.text(
        (width // 2, 220),
        f"SCENE {scene_number:02d}",
        fill=accent_color,
        font=font_medium,
        anchor="mm",
    )
    draw.text(
        (width // 2, 260),
        scene_title.upper(),
        fill=(255, 255, 255),
        font=font_medium,
        anchor="mm",
    )

    # Speaker & Voice Badge
    badge_text = f"[{speaker.upper()}] • {voice_name}"
    draw.rectangle(
        [(width // 2 - 200, 320), (width // 2 + 200, 355)],
        fill=(20, 25, 45),
        outline=accent_color,
        width=1,
    )
    draw.text(
        (width // 2, 337),
        badge_text,
        fill=(240, 240, 255),
        font=font_small,
        anchor="mm",
    )

    # Dialogue Box Overlay in lower third
    box_top = height - 420
    box_bottom = height - 150
    draw.rectangle(
        [(60, box_top), (width - 60, box_bottom)],
        fill=(10, 15, 28),
        outline=(80, 90, 120),
        width=1,
    )

    # Wrap dialogue text into lines
    chars_per_line = 36
    words = dialogue.split()
    lines: list[str] = []
    current_line = []
    current_len = 0
    for w in words:
        if current_len + len(w) + 1 > chars_per_line:
            lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)
        else:
            current_line.append(w)
            current_len += len(w) + 1
    if current_line:
        lines.append(" ".join(current_line))

    start_y = box_top + 35
    for line in lines[:8]:
        draw.text(
            (width // 2, start_y),
            line,
            fill=(250, 250, 250),
            font=font_medium,
            anchor="mm",
        )
        start_y += 32

    # Footer
    draw.text(
        (width // 2, height - 70),
        "9:16 VERTICAL CINEMATIC VIDEO • STEREO AUDIO",
        fill=(140, 150, 180),
        font=font_small,
        anchor="mm",
    )

    img.save(output_path, "PNG")
    return output_path


async def fetch_image_from_bridge(
    prompt: str,
    output_path: str,
    server_url: str = "http://127.0.0.1:8001/v1",
) -> bool:
    """Fetch image generated by local image bridge on port 8001."""
    import base64
    import urllib.request

    url = f"{server_url.rstrip('/')}/images/generations"
    payload = json.dumps({"prompt": prompt, "size": "720x1280"}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            headers={"Content-Type": "application/json"},
            data=payload,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            b64_img = data["data"][0]["b64_json"]
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(b64_img))
            return True
    except Exception as e:
        print(f"  [ImageBridge Info] Bridge request failed ({e}), using local renderer")
        return False


async def synthesize_speech(
    text: str,
    voice: str,
    audio_path: str,
) -> Tuple[str, str, float]:
    """Synthesize speech audio and matching SRT subtitles using Edge-TTS."""
    os.makedirs(os.path.dirname(audio_path), exist_ok=True)
    srt_path = audio_path.rsplit(".", 1)[0] + ".srt"

    # Resolve voice alias if applicable
    resolved_voice = EDGE_VOICE_ALIASES.get(voice, voice)
    print(f"  [TTS] Synthesizing ({resolved_voice}): \"{text[:45]}...\"")

    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, resolved_voice)
        submaker = edge_tts.SubMaker()

        with open(audio_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "SentenceBoundary":
                    submaker.feed(chunk)

        duration = get_audio_duration(audio_path)
        srt_content = submaker.get_srt()

        # If submaker produced empty srt, generate timed srt from audio duration
        if not srt_content.strip():
            ms = int(duration * 1000)
            sec = ms // 1000
            rem_ms = ms % 1000
            srt_content = (
                f"1\n"
                f"00:00:00,100 --> 00:00:{sec:02d},{rem_ms:03d}\n"
                f"{text}\n\n"
            )

        Path(srt_path).write_text(srt_content, encoding="utf-8")
        return audio_path, srt_path, duration

    except Exception as exc:
        print(f"  [Warning] Edge-TTS stream error ({exc}), using resilient fallback synthesis")
        duration = max(2.5, len(text) * 0.08)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=44100:cl=stereo:d={duration:.2f}",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                audio_path,
            ],
            check=True,
            capture_output=True,
        )
        ms = int(duration * 1000)
        sec = ms // 1000
        rem_ms = ms % 1000
        srt_content = (
            f"1\n"
            f"00:00:00,100 --> 00:00:{sec:02d},{rem_ms:03d}\n"
            f"{text}\n\n"
        )
        Path(srt_path).write_text(srt_content, encoding="utf-8")
        return audio_path, srt_path, duration


async def generate_pilot_episode(language: str = "fr", output_file: str | None = None) -> str:
    """Orchestrates end-to-end pilot episode generation in French or English."""
    lang = (language or "fr").lower().strip()
    print("=" * 70)
    print(f"🎬 DRAMACLAW: RUNNING PILOT EPISODE GENERATION ({lang.upper()})")
    print("=" * 70)

    work_dir = REPO_ROOT / "data" / "runtime" / f"pilot_{lang}"
    output_dir = REPO_ROOT / "data" / "output"
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    target_video_path = output_file or str(output_dir / f"pilot_episode_{lang}.mp4")

    # Story definition with multi-character roles
    if lang == "fr":
        # French Story: "L'Ombre de la Forêt Enchantée"
        beats = [
            {
                "scene_number": 1,
                "scene_title": "Les Murmures de la Forêt",
                "speaker": "Narrateur",
                "voice": get_edge_voice("fr", role="narrator"),
                "dialogue": "Au cœur des terres brumeuses de Val-Serein, les anciens arbres murmurent d'étranges prophéties à quiconque ose s'aventurer dans l'obscurité.",
                "top_color": (12, 16, 32),
                "bottom_color": (28, 38, 70),
                "accent_color": (100, 180, 255),
                "effect": KenBurnsEffect.ZOOM_IN,
            },
            {
                "scene_number": 2,
                "scene_title": "La Découverte d'Éléonore",
                "speaker": "Éléonore",
                "voice": get_edge_voice("fr", role="female", gender="female"),
                "dialogue": "Regarde cette clairière... Le talisman des étoiles s'est réveillé. La prophétie était donc vraie !",
                "top_color": (10, 28, 32),
                "bottom_color": (20, 68, 78),
                "accent_color": (70, 240, 210),
                "effect": KenBurnsEffect.PAN_LEFT,
            },
            {
                "scene_number": 3,
                "scene_title": "L'Avertissement Sylvain",
                "speaker": "L'Esprit Sylvain",
                "voice": get_edge_voice("fr", role="child", age_group="child"),
                "dialogue": "Prends garde, Éléonore ! L'amulette pulse d'une force ancienne et instable. Ne la touche pas avant l'aube !",
                "top_color": (32, 22, 10),
                "bottom_color": (76, 50, 18),
                "accent_color": (255, 195, 75),
                "effect": KenBurnsEffect.ZOOM_OUT,
            },
            {
                "scene_number": 4,
                "scene_title": "Le Destin Scellé",
                "speaker": "Narrateur",
                "voice": get_edge_voice("fr", role="narrator"),
                "dialogue": "Unis par le serment des étoiles, ils scellèrent l'énergie du talisman avant les premières lueurs du jour. Une nouvelle ère commençait.",
                "top_color": (36, 12, 30),
                "bottom_color": (95, 45, 65),
                "accent_color": (255, 140, 160),
                "effect": KenBurnsEffect.ZOOM_IN,
            },
        ]
    else:
        # English Story: "The Legend of the Whispering Grove"
        beats = [
            {
                "scene_number": 1,
                "scene_title": "The Whispering Woods",
                "speaker": "Narrator",
                "voice": get_edge_voice("en", role="narrator"),
                "dialogue": "Deep within the shrouded mist of Eldoria, ancient sentinels whisper forgotten secrets to those bold enough to enter.",
                "top_color": (12, 16, 32),
                "bottom_color": (28, 38, 70),
                "accent_color": (100, 180, 255),
                "effect": KenBurnsEffect.ZOOM_IN,
            },
            {
                "scene_number": 2,
                "scene_title": "The Astral Discovery",
                "speaker": "Lady Jenny",
                "voice": get_edge_voice("en", role="female", gender="female"),
                "dialogue": "Behold the sanctuary... The legendary Star Talisman is awakening. The chronicles spoke the truth!",
                "top_color": (10, 28, 32),
                "bottom_color": (20, 68, 78),
                "accent_color": (70, 240, 210),
                "effect": KenBurnsEffect.PAN_LEFT,
            },
            {
                "scene_number": 3,
                "scene_title": "The Sprite's Warning",
                "speaker": "Sprite Ana",
                "voice": get_edge_voice("en", role="child", age_group="child"),
                "dialogue": "Careful, Jenny! The artifact's energy is surging uncontrollably. We must bind it before sunrise!",
                "top_color": (32, 22, 10),
                "bottom_color": (76, 50, 18),
                "accent_color": (255, 195, 75),
                "effect": KenBurnsEffect.ZOOM_OUT,
            },
            {
                "scene_number": 4,
                "scene_title": "Dawn of Destiny",
                "speaker": "Narrator",
                "voice": get_edge_voice("en", role="narrator"),
                "dialogue": "Harmonizing the elemental stones at last, peace was restored across the realm as golden light crowned the peaks.",
                "top_color": (36, 12, 30),
                "bottom_color": (95, 45, 65),
                "accent_color": (255, 140, 160),
                "effect": KenBurnsEffect.ZOOM_IN,
            },
        ]

    # Step 1: Generate Visual Frames and TTS Audio + Subtitles
    print("\n[Phase 1/3] Generating Visuals & Synthesizing Audio...")
    scene_assets: list[SceneAsset] = []
    scene_clips: list[str] = []

    composer = VideoComposer(width=720, height=1280, fps=30)

    for b in beats:
        idx = b["scene_number"]
        img_path = str(work_dir / f"scene_{idx:02d}.png")
        audio_path = str(work_dir / f"scene_{idx:02d}.mp3")

        # Generate Frame (via local image bridge on port 8001, with procedural fallback)
        prompt_desc = f"{b['scene_title']} - {b['speaker']}: {b['dialogue']}"
        bridge_ok = await fetch_image_from_bridge(prompt_desc, img_path)
        if not bridge_ok:
            create_gradient_frame(
                width=720,
                height=1280,
                top_color=b["top_color"],
                bottom_color=b["bottom_color"],
                accent_color=b["accent_color"],
                scene_number=idx,
                scene_title=b["scene_title"],
                speaker=b["speaker"],
                voice_name=b["voice"],
                dialogue=b["dialogue"],
                output_path=img_path,
            )

        # Synthesize Audio & Subtitle
        a_path, s_path, duration = await synthesize_speech(
            text=b["dialogue"],
            voice=b["voice"],
            audio_path=audio_path,
        )

        asset = SceneAsset(
            scene_number=idx,
            image_path=img_path,
            audio_path=a_path,
            subtitle_path=s_path,
            duration_seconds=duration,
            narration_text=b["dialogue"],
        )
        scene_assets.append(asset)

    # Step 2: Render Scene Video Clips with Ken Burns & Subtitle Burn-In
    print("\n[Phase 2/3] Rendering Scene Clips & Burning Subtitles with FFmpeg...")
    for i, (b, asset) in enumerate(zip(beats, scene_assets)):
        idx = asset.scene_number
        raw_clip = str(work_dir / f"clip_raw_{idx:02d}.mp4")
        sub_clip = str(work_dir / f"clip_sub_{idx:02d}.mp4")

        print(f"  🎬 Rendering Clip {idx:02d} (Duration: {asset.duration_seconds:.2f}s, Effect: {b['effect']})")
        clip_ok = await composer._create_scene_video(
            scene=asset,
            output_path=raw_clip,
            effect=b["effect"],
        )
        if not clip_ok or not os.path.isfile(raw_clip):
            raise RuntimeError(f"Failed to create video clip for scene {idx}")

        # Burn subtitles into this scene clip
        sub_res = await composer.add_subtitles(
            video_path=raw_clip,
            subtitle_path=asset.subtitle_path,
            output_path=sub_clip,
            style="FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Shadow=1,Alignment=2,MarginV=60",
        )
        if not sub_res.success or not os.path.isfile(sub_clip):
            print(f"  [Notice] Subtitle burn-in returned notice, using clean raw clip: {sub_res.error}")
            scene_clips.append(raw_clip)
        else:
            scene_clips.append(sub_clip)

    # Step 3: Concatenate Scene Clips into Final Episode
    print("\n[Phase 3/3] Assembling Final Episode...")
    concat_ok = await composer._concat_videos(scene_clips, target_video_path)
    if not concat_ok or not os.path.isfile(target_video_path):
        raise RuntimeError(f"Failed to concatenate final video to {target_video_path}")

    # Step 4: Verification with ffprobe
    print("\n[Validation] Inspecting output media with ffprobe...")
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=codec_name,codec_type,width,height",
        "-of",
        "json",
        target_video_path,
    ]
    probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    probe_data = json.loads(probe_res.stdout)

    format_info = probe_data.get("format", {})
    streams_info = probe_data.get("streams", [])
    duration_sec = float(format_info.get("duration", 0.0))
    size_bytes = int(format_info.get("size", 0))

    has_video = any(s.get("codec_type") == "video" for s in streams_info)
    has_audio = any(s.get("codec_type") == "audio" for s in streams_info)

    print("-" * 70)
    print(f"✅ PILOT EPISODE GENERATED SUCCESSFULLY!")
    print(f"   • Path: {target_video_path}")
    print(f"   • Size: {size_bytes / 1024:.1f} KB ({size_bytes} bytes)")
    print(f"   • Duration: {duration_sec:.2f} seconds")
    print(f"   • Video Stream: {'YES' if has_video else 'NO'}")
    print(f"   • Audio Stream: {'YES' if has_audio else 'NO'}")
    print(f"   • Streams Count: {len(streams_info)}")
    print("-" * 70)

    if not has_video or not has_audio or duration_sec < 1.0 or size_bytes < 50_000:
        raise ValueError(f"Generated video failed quality gate: {target_video_path}")

    return target_video_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DramaClaw Multi-Language Pilot Episode")
    parser.add_argument(
        "--lang",
        choices=["fr", "en"],
        default="fr",
        help="Target language for voices and script (fr or en, default: fr)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output file path for the final MP4",
    )
    args = parser.parse_args()

    asyncio.run(generate_pilot_episode(language=args.lang, output_file=args.output))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""DramaClaw Headless Autonomous Episodic Drama Engine (Max 3 Min).

Generates 2-part serialized video stories (18 shots total, ~2.5 to 3 minutes) headlessly:
1. Visual style presets (kids_pixar, kids_storybook, drama_cinematic)
2. Character visual identity locking & 2-chapter structure (Part 1 Cliffhanger & Part 2 Outro)
3. Dual 3x3 composite grid generation & grid_splitter slicing (18 clean frames)
4. Multi-voice Edge-TTS synthesis & SRT subtitle generation
5. Dynamic video assembly with Ken Burns effects, BGM audio mixing (-15dB), and Part 1/Part 2 or Unified exports
"""

import argparse
import asyncio
import base64
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Optional

from PIL import Image

# Ensure project imports resolve
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from novelvideo.generators.grid_splitter import split_grid
from novelvideo.generators.video_composer import VideoComposer, SceneAsset

# Visual Presets
STYLE_PRESETS = {
    "kids_pixar": (
        "3D Pixar animation style, cute character, expressive big eyes, soft velvety lighting, "
        "vibrant saturated colors, 8k render"
    ),
    "kids_storybook": (
        "Whimsical watercolor children's book illustration, soft pastel colors, gentle outlines, "
        "cozy fairytale aesthetic"
    ),
    "drama_cinematic": (
        "Cinematic 9:16 vertical framing, shallow depth of field, dramatic rim lighting, "
        "film grain, intense emotional atmosphere"
    ),
}

# Multi-language voice profiles
VOICE_PROFILES = {
    "fr": {
        "narrator": "fr-FR-HenriNeural",
        "lead_adult": "fr-FR-VivienneNeural",
        "child": "fr-FR-EloiseNeural",
    },
    "en": {
        "narrator": "en-US-ChristopherNeural",
        "lead_adult": "en-US-JennyNeural",
        "child": "en-US-AnaNeural",
    },
}

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434/v1")
DEFAULT_IMAGE_SERVER_URL = os.environ.get("IMAGE_API_BASE", "http://127.0.0.1:8001/v1/images/generations")


def call_ollama_json(prompt: str, system_prompt: str, model: str = "qwen2.5:14b") -> Dict[str, Any]:
    """Call Ollama via OpenAI-compatible or native endpoints for structured JSON output."""
    base = DEFAULT_OLLAMA_URL.rstrip("/")
    endpoints = [
        f"{base}/chat/completions",
        "http://localhost:11434/api/chat",
        "http://localhost:11434/api/generate",
    ]

    for url in endpoints:
        try:
            if "chat" in url:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "format": "json",
                    "stream": False,
                }
            else:
                payload = {
                    "model": model,
                    "prompt": f"{system_prompt}\n\nTask: {prompt}",
                    "format": "json",
                    "stream": False,
                }

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "choices" in data:
                    content = data["choices"][0]["message"]["content"]
                elif "message" in data:
                    content = data["message"]["content"]
                elif "response" in data:
                    content = data["response"]
                else:
                    continue
                return json.loads(content)
        except Exception:
            continue

    print("[Ollama] Local LLM unreachable, using structured episodic fallback generator")
    return generate_fallback_episodic_storyboard(prompt)


def generate_fallback_episodic_storyboard(topic: str) -> Dict[str, Any]:
    """Generate a 18-beat (2-chapter) fallback storyboard structure with character lock."""
    char_desc = "Cute small brown kitten with wide green eyes, soft fluffy fur, wearing a tiny red neckerchief"
    
    part1_beats = [
        {
            "beat_number": 1,
            "character_role": "narrator",
            "dialogue": f"Voici l'histoire de {topic}. La nuit tombait sur le village.",
            "visual_prompt": f"Panel 1: {char_desc} looking curiously at a cozy village sunset",
        },
        {
            "beat_number": 2,
            "character_role": "child",
            "dialogue": "J'ai un peu peur des ombres qui s'allongent dans ma chambre...",
            "visual_prompt": f"Panel 2: Close up of {char_desc} with wide timid green eyes in dim room",
        },
        {
            "beat_number": 3,
            "character_role": "narrator",
            "dialogue": "Mais une drôle de lueur dorée s'alluma sous le tapis de l'entrée.",
            "visual_prompt": f"Panel 3: {char_desc} creeping towards a golden glowing keyhole on the floor",
        },
        {
            "beat_number": 4,
            "character_role": "child",
            "dialogue": "Regarde ! Qu'est-ce que c'est que cette lumière brillante ?",
            "visual_prompt": f"Panel 4: {char_desc} pointing paw at sparkling golden light beam",
        },
        {
            "beat_number": 5,
            "character_role": "lead_adult",
            "dialogue": "C'est la légende de la nuit magique, mon petit explorateur.",
            "visual_prompt": f"Panel 5: Kind elder cat sitting next to {char_desc} in warm study",
        },
        {
            "beat_number": 6,
            "character_role": "narrator",
            "dialogue": "Le petit chat s'avança doucement et poussa la porte secrète.",
            "visual_prompt": f"Panel 6: {char_desc} stepping through a glowing mystical wooden doorway",
        },
        {
            "beat_number": 7,
            "character_role": "child",
            "dialogue": "Wow ! Un jardin d'étoiles scintillantes !",
            "visual_prompt": f"Panel 7: Wide shot of {char_desc} amazed in magical glowing garden",
        },
        {
            "beat_number": 8,
            "character_role": "narrator",
            "dialogue": "Au centre du jardin, un coffre magique se mit à trembler doucement.",
            "visual_prompt": f"Panel 8: {char_desc} approaching a floating golden chest with stars",
        },
        {
            "beat_number": 9,
            "character_role": "narrator",
            "dialogue": "Soudain, la serrure cliqueta ! Que va-t-il découvrir dans ce coffre secret ? La suite dans la Partie 2 !",
            "visual_prompt": f"Panel 9: Dramatic cliffhanger shot of {char_desc} opening glittering treasure chest",
        },
    ]

    part2_beats = [
        {
            "beat_number": 10,
            "character_role": "narrator",
            "dialogue": "Bienvenue dans la Partie 2 ! Le coffre s'ouvre enfin devant le petit chat.",
            "visual_prompt": f"Panel 1: {char_desc} watching glowing light erupting from the treasure chest",
        },
        {
            "beat_number": 11,
            "character_role": "child",
            "dialogue": "Regarde toutes ces lucioles qui dansent dans l'air !",
            "visual_prompt": f"Panel 11: {char_desc} surrounded by dozens of playful glowing fireflies",
        },
        {
            "beat_number": 12,
            "character_role": "narrator",
            "dialogue": "Chaque luciole apportait une douce lanterne pour éclairer la nuit.",
            "visual_prompt": f"Panel 12: Fireflies forming a glowing starry path for {char_desc}",
        },
        {
            "beat_number": 13,
            "character_role": "child",
            "dialogue": "La nuit n'est pas sombre... elle est remplie de magie !",
            "visual_prompt": f"Panel 13: {char_desc} smiling happily under starry magical sky",
        },
        {
            "beat_number": 14,
            "character_role": "lead_adult",
            "dialogue": "Tu as surmonté ta peur avec beaucoup de courage !",
            "visual_prompt": f"Panel 14: Elder mentor cat hugging {char_desc} warmly",
        },
        {
            "beat_number": 15,
            "character_role": "narrator",
            "dialogue": "Le petit explorateur garda la clé dorée en souvenir de cette belle aventure.",
            "visual_prompt": f"Panel 15: Close up of {char_desc} holding sparkling golden key necklace",
        },
        {
            "beat_number": 16,
            "character_role": "child",
            "dialogue": "Désormais, je n'aurai plus jamais peur du noir !",
            "visual_prompt": f"Panel 16: {char_desc} sleeping peacefully in cozy bed with golden key glowing",
        },
        {
            "beat_number": 17,
            "character_role": "narrator",
            "dialogue": "Et c'est ainsi que la nuit devint sa période préférée pour rêver.",
            "visual_prompt": f"Panel 17: Wide moonlit house window view with soft magical glow",
        },
        {
            "beat_number": 18,
            "character_role": "narrator",
            "dialogue": "Aime la vidéo et abonne-toi pour découvrir la prochaine grande aventure !",
            "visual_prompt": f"Panel 18: Outro graphic shot with {char_desc} waving happy goodbye",
        },
    ]

    return {
        "title": topic,
        "character_lock": char_desc,
        "part1_beats": part1_beats,
        "part2_beats": part2_beats,
    }


def call_local_image_generator(prompt: str, width: int = 1536, height: int = 1536) -> bytes:
    """Generate composite 3x3 grid image via local image bridge server."""
    payload = {
        "prompt": prompt,
        "size": f"{width}x{height}",
        "engine": "fast",
    }
    
    req = urllib.request.Request(
        DEFAULT_IMAGE_SERVER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    
    print(f"[ImageGen] Requesting 3x3 Grid Image ({width}x{height})...")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        b64_json = data["data"][0]["b64_json"]
        return base64.b64decode(b64_json)


async def synthesize_edge_tts(text: str, voice: str, output_mp3: Path) -> float:
    """Synthesize speech using Edge-TTS and return precise duration in seconds."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_mp3))

    try:
        from moviepy.editor import AudioFileClip
        with AudioFileClip(str(output_mp3)) as clip:
            return max(1.8, float(clip.duration))
    except Exception:
        words = len(text.split())
        return max(2.5, words * 0.45)


def create_srt_file(text: str, duration: float, srt_path: Path):
    """Write formatted SRT subtitle file."""
    def format_time(seconds: float) -> str:
        millis = int((seconds - int(seconds)) * 1000)
        secs = int(seconds) % 60
        mins = (int(seconds) // 60) % 60
        hrs = int(seconds) // 3600
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    srt_content = f"1\n00:00:00,000 --> {format_time(duration)}\n{text}\n"
    srt_path.write_text(srt_content, encoding="utf-8")


def construct_nanobanana_grid_prompt(
    topic: str,
    part_num: int,
    style_prompt: str,
    char_lock: str,
    beats: List[Dict[str, Any]],
) -> str:
    """Construct 3x3 storyboard composite prompt following nanobanana_grid specifications."""
    prompt_lines = [
        f"Generate a 3x3 storyboard grid (3 rows by 3 columns, 9 panels total) for Part {part_num} of '{topic}'.",
        f"Style: {style_prompt}.",
        f"Unified Main Character Appearance Lock: {char_lock}.",
        "Grid Layout:",
        "+------------+------------+------------+",
        "|  Panel 1   |  Panel 2   |  Panel 3   |",
        "+------------+------------+------------+",
        "|  Panel 4   |  Panel 5   |  Panel 6   |",
        "+------------+------------+------------+",
        "|  Panel 7   |  Panel 8   |  Panel 9   |",
        "+------------+------------+------------+",
        "Panel Visual Breakdowns:",
    ]

    for idx, b in enumerate(beats[:9]):
        panel_num = idx + 1
        desc = b.get("visual_prompt", f"Beat {panel_num} scene")
        prompt_lines.append(f"[Panel {panel_num}]: {desc}")

    return "\n".join(prompt_lines)


def mix_background_audio(video_path: str, output_path: str, genre: str = "kids") -> bool:
    """Mix low-volume (-15dB / volume=0.15) background music into video using FFmpeg."""
    # Synthetic ambient BGM audio generator string
    if genre == "kids":
        bgm_filter = (
            "aevalsrc='sin(2*PI*440*t)*0.03 + sin(2*PI*554.37*t)*0.02 + "
            "sin(2*PI*659.25*t)*0.02:s=44100'"
        )
    else:
        bgm_filter = (
            "aevalsrc='sin(2*PI*110*t)*0.04 + sin(2*PI*164.81*t)*0.03:s=44100'"
        )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-f",
        "lavfi",
        "-i",
        bgm_filter,
        "-filter_complex",
        "[1:a]volume=0.15[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        output_path,
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[BGM] Mixing failed ({e}), retaining original audio")
        return False


async def run_episodic_pipeline(
    topic: str,
    genre: str = "kids",
    style: Optional[str] = None,
    export_mode: str = "parts",
    lang: str = "fr",
    output_dir: str = "data/output",
):
    # Select style preset
    if not style:
        style = "kids_pixar" if genre == "kids" else "drama_cinematic"
    style_prompt = STYLE_PRESETS.get(style, STYLE_PRESETS["kids_pixar"])

    print(f"==================================================")
    print(f"🚀 DRAMACLAW AUTONOMOUS EPISODIC ENGINE (MAX 3 MIN)")
    print(f"Topic: '{topic}'")
    print(f"Genre: {genre} | Style: {style} | Export: {export_mode} | Lang: {lang}")
    print(f"==================================================")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    temp_dir = out_path / f"temp_ep_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # STEP A: Generate 2-Chapter Script & Storyboard via LLM
    # -------------------------------------------------------------------------
    print("\n[Step A] Generating 2-Chapter Storyboard (18 Beats) & Character Lock via LLM...")
    system_prompt = (
        "You are a master storyteller. Produce a 2-chapter (18-beat) video storyboard in JSON format.\n"
        "Return a JSON object with keys:\n"
        '{\n'
        '  "title": "Story Title",\n'
        '  "character_lock": "Detailed visual description of main character (clothing, hair, colors)",\n'
        '  "part1_beats": [ {"beat_number": 1, "character_role": "narrator|child|lead_adult", "dialogue": "...", "visual_prompt": "..."} ],\n'
        '  "part2_beats": [ {"beat_number": 10, "character_role": "narrator|child|lead_adult", "dialogue": "...", "visual_prompt": "..."} ]\n'
        '}\n'
        "Part 1 must end on beat 9 with a cliffhanger and call-to-action ('La suite dans la partie 2 !').\n"
        "Part 2 must end on beat 18 with a morale/outro ('Abonne-toi !').\n"
        f"Language: {lang.upper()}. Exactly 9 beats per part."
    )
    user_prompt = f"Create a 2-part {genre} story about: '{topic}'"

    story_data = call_ollama_json(user_prompt, system_prompt)
    char_lock = story_data.get("character_lock", "Cute main character with distinct outfit")
    part1_beats = story_data.get("part1_beats", [])
    part2_beats = story_data.get("part2_beats", [])

    if len(part1_beats) < 9 or len(part2_beats) < 9:
        print("[Engine] Incomplete LLM output, applying fallback 18-beat storyboard...")
        fallback = generate_fallback_episodic_storyboard(topic)
        char_lock = fallback["character_lock"]
        part1_beats = fallback["part1_beats"]
        part2_beats = fallback["part2_beats"]

    # -------------------------------------------------------------------------
    # STEP B: Dual 3x3 Grid Image Generation & Splitting (18 Shots)
    # -------------------------------------------------------------------------
    print("\n[Step B] Generating Dual 3x3 Composite Grid Images (Part 1 & Part 2)...")
    
    grid1_prompt = construct_nanobanana_grid_prompt(topic, 1, style_prompt, char_lock, part1_beats)
    grid2_prompt = construct_nanobanana_grid_prompt(topic, 2, style_prompt, char_lock, part2_beats)

    grid1_bytes = call_local_image_generator(grid1_prompt, width=1536, height=1536)
    grid2_bytes = call_local_image_generator(grid2_prompt, width=1536, height=1536)

    (temp_dir / "grid_part1.png").write_bytes(grid1_bytes)
    (temp_dir / "grid_part2.png").write_bytes(grid2_bytes)

    print("[Step B.2] Splitting Grids into 18 Shot Frames via grid_splitter...")
    shots_p1 = split_grid(grid1_bytes, temp_dir / "shots_p1", rows=3, cols=3, prefix="p1_shot_")
    shots_p2 = split_grid(grid2_bytes, temp_dir / "shots_p2", rows=3, cols=3, prefix="p2_shot_")

    # -------------------------------------------------------------------------
    # STEP C: Audio & Subtitle Synthesis for All 18 Beats
    # -------------------------------------------------------------------------
    print("\n[Step C] Synthesizing Multi-Voice Audio & SRT Subtitles...")
    voices = VOICE_PROFILES.get(lang, VOICE_PROFILES["fr"])

    async def process_beats(beats: List[Dict[str, Any]], shots: List[Path], prefix: str) -> List[SceneAsset]:
        scenes: List[SceneAsset] = []
        for idx, beat in enumerate(beats[:9]):
            num = idx + 1
            role = beat.get("character_role", "narrator")
            voice_id = voices.get(role, voices["narrator"])
            dialogue = beat.get("dialogue", f"Scène {num}")

            mp3_p = temp_dir / f"{prefix}_audio_{num:02d}.mp3"
            srt_p = temp_dir / f"{prefix}_sub_{num:02d}.srt"

            duration = await synthesize_edge_tts(dialogue, voice_id, mp3_p)
            create_srt_file(dialogue, duration, srt_p)

            img_p = str(shots[idx]) if idx < len(shots) else str(shots[0])

            scenes.append(
                SceneAsset(
                    scene_number=num,
                    image_path=img_p,
                    audio_path=str(mp3_p),
                    subtitle_path=str(srt_p),
                    duration_seconds=duration,
                    narration_text=dialogue,
                )
            )
        return scenes

    scenes_p1 = await process_beats(part1_beats, shots_p1, "p1")
    scenes_p2 = await process_beats(part2_beats, shots_p2, "p2")

    # -------------------------------------------------------------------------
    # STEP D: Video Assembly & BGM Mixing
    # -------------------------------------------------------------------------
    print("\n[Step D] Assembling Videos & Mixing Background Audio (BGM -15dB)...")
    composer = VideoComposer(width=720, height=1280, fps=30)
    clean_title = re.sub(r"[^\w\-_]", "_", topic.lower())

    if export_mode == "parts":
        raw_p1 = str(temp_dir / "raw_part1.mp4")
        raw_p2 = str(temp_dir / "raw_part2.mp4")

        final_p1 = out_path / f"episode_{clean_title}_part1.mp4"
        final_p2 = out_path / f"episode_{clean_title}_part2.mp4"

        res1 = await composer.compose_episode(scenes_p1, raw_p1, title=f"{topic} (Partie 1)")
        res2 = await composer.compose_episode(scenes_p2, raw_p2, title=f"{topic} (Partie 2)")

        if res1.success:
            mix_background_audio(raw_p1, str(final_p1), genre)
        if res2.success:
            mix_background_audio(raw_p2, str(final_p2), genre)

        print("\n==================================================")
        print("🎉 SUCCESS! Rendered 2-Part Serialized Episodes:")
        print(f"   📁 Part 1: {final_p1.resolve()} ({res1.duration_seconds:.1f}s)")
        print(f"   📁 Part 2: {final_p2.resolve()} ({res2.duration_seconds:.1f}s)")
        print("==================================================")

    else:
        all_scenes = scenes_p1 + scenes_p2
        raw_unified = str(temp_dir / "raw_unified.mp4")
        final_unified = out_path / f"episode_{clean_title}_complete.mp4"

        res = await composer.compose_episode(all_scenes, raw_unified, title=topic)
        if res.success:
            mix_background_audio(raw_unified, str(final_unified), genre)

        print("\n==================================================")
        print("🎉 SUCCESS! Rendered Unified Complete Episode:")
        print(f"   📁 Complete: {final_unified.resolve()} ({res.duration_seconds:.1f}s)")
        print("==================================================")


def main():
    parser = argparse.ArgumentParser(description="DramaClaw Headless Episodic Drama Engine")
    parser.add_argument("--topic", type=str, required=True, help="Story topic / prompt")
    parser.add_argument("--genre", type=str, default="kids", choices=["kids", "drama"], help="Genre preset")
    parser.add_argument(
        "--style",
        type=str,
        default=None,
        choices=["kids_pixar", "kids_storybook", "drama_cinematic"],
        help="Visual style preset",
    )
    parser.add_argument(
        "--export-mode",
        type=str,
        default="parts",
        choices=["parts", "unified"],
        help="Export mode: 'parts' (Part 1 / Part 2) or 'unified' (single 3-min video)",
    )
    parser.add_argument("--lang", type=str, default="fr", choices=["fr", "en"], help="Target language")
    parser.add_argument("--output-dir", type=str, default="data/output", help="Output directory")

    args = parser.parse_args()
    asyncio.run(
        run_episodic_pipeline(
            args.topic,
            args.genre,
            args.style,
            args.export_mode,
            args.lang,
            args.output_dir,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""DramaClaw Headless Autonomous Drama Engine.

Generates complete 9-beat video stories headlessly from a single prompt:
1. Script & Beats generation via Ollama (qwen2.5:14b)
2. Consistent visual grid generation (3x3 nanobanana prompt format via local image server)
3. Smart grid slicing via grid_splitter
4. Multi-voice dialogue audio synthesis via Edge-TTS + SRT generator
5. Dynamic video assembly with Ken Burns effect & burn-in subtitles via VideoComposer
"""

import argparse
import asyncio
import io
import json
import math
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Any

from PIL import Image

# Ensure project imports resolve
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from novelvideo.generators.grid_splitter import split_grid
from novelvideo.generators.video_composer import VideoComposer, SceneAsset

# Edge-TTS multi-language voice profiles
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
    """Call Ollama via OpenAI-compatible or native endpoint expecting JSON response."""
    base = DEFAULT_OLLAMA_URL.rstrip('/')
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
        except Exception as e:
            continue
            
    print(f"[Ollama] LLM service unreachable on local endpoints, using structured storyboard generator")
    return generate_fallback_storyboard(prompt)


def generate_fallback_storyboard(topic: str) -> Dict[str, Any]:
    """Provide structured fallback beats if LLM is unreachable."""
    print("[Engine] Using fallback structured storyboard")
    return {
        "title": topic,
        "characters": [
            {"name": "Explorer", "role": "child", "description": "Young adventurous boy with blue cap"},
            {"name": "Mentor", "role": "lead_adult", "description": "Wise old man with brown coat"},
        ],
        "beats": [
            {
                "beat_number": i + 1,
                "character": "Explorer" if i % 2 == 0 else "Mentor",
                "dialogue": f"Beat {i+1}: Journey step for {topic}",
                "visual_prompt": f"Panel {i+1}: Cinematic scene illustrating {topic}, shot {i+1}",
                "camera_effect": "zoom_in" if i % 2 == 0 else "pan_right",
            }
            for i in range(9)
        ],
    }


def call_local_image_generator(prompt: str, width: int = 1536, height: int = 1536) -> bytes:
    """Generate a single composite image from local image bridge server."""
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
        import base64
        b64_json = data["data"][0]["b64_json"]
        return base64.b64decode(b64_json)


async def synthesize_edge_tts(text: str, voice: str, output_mp3: Path) -> float:
    """Synthesize speech using edge-tts python module and return duration in seconds."""
    import edge_tts
    
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_mp3))
    
    # Calculate audio duration via FFmpeg / moviepy if available or file size approximation
    try:
        from moviepy.editor import AudioFileClip
        with AudioFileClip(str(output_mp3)) as clip:
            return max(1.5, float(clip.duration))
    except Exception:
        # Fallback duration calculation from words count
        words = len(text.split())
        return max(2.0, words * 0.4)


def create_srt_file(text: str, duration: float, srt_path: Path):
    """Write simple SRT subtitle file for a scene duration."""
    def format_time(seconds: float) -> str:
        millis = int((seconds - int(seconds)) * 1000)
        secs = int(seconds) % 60
        mins = (int(seconds) // 60) % 60
        hrs = int(seconds) // 3600
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    srt_content = f"1\n00:00:00,000 --> {format_time(duration)}\n{text}\n"
    srt_path.write_text(srt_content, encoding="utf-8")


def construct_nanobanana_grid_prompt(topic: str, genre: str, beats: List[Dict[str, Any]]) -> str:
    """Construct 3x3 storyboard composite prompt following nanobanana_grid specifications."""
    style_keywords = (
        "3D Pixar animated kids style, vibrant colors, expressive characters, warm lighting"
        if genre == "kids"
        else "Cinematic dramatic film style, atmospheric noir lighting, rich textures, high contrast"
    )
    
    prompt_lines = [
        f"Generate a 3x3 storyboard grid (3 rows by 3 columns, 9 panels total) for a {genre} story titled '{topic}'.",
        f"Style: {style_keywords}.",
        "Grid Layout:",
        "+------------+------------+------------+",
        "|  Panel 1   |  Panel 2   |  Panel 3   |",
        "+------------+------------+------------+",
        "|  Panel 4   |  Panel 5   |  Panel 6   |",
        "+------------+------------+------------+",
        "|  Panel 7   |  Panel 8   |  Panel 9   |",
        "+------------+------------+------------+",
        "Consistent Character Identity Lock across all 9 panels.",
        "Panel Visual Breakdowns:",
    ]
    
    for b in beats:
        num = b.get("beat_number", 1)
        desc = b.get("visual_prompt", f"Beat {num} scene")
        prompt_lines.append(f"[Panel {num}]: {desc}")
        
    return "\n".join(prompt_lines)


async def run_autonomous_pipeline(topic: str, genre: str = "kids", lang: str = "fr", output_dir: str = "data/output"):
    print(f"==================================================")
    print(f"🚀 DRAMACLAW AUTONOMOUS ENGINE")
    print(f"Topic: '{topic}' | Genre: {genre} | Lang: {lang}")
    print(f"==================================================")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    temp_dir = out_path / f"temp_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # STEP A: Script & Storyboard Generation via LLM
    # -------------------------------------------------------------------------
    print("\n[Step A] Generating Script & 9-Beat Storyboard via LLM...")
    system_prompt = (
        "You are an expert director and screenwriter. Produce a 9-beat storyboard in JSON format.\n"
        "Return a JSON object matching:\n"
        "{\n"
        '  "title": "Story Title",\n'
        '  "characters": [{"name": "CharName", "role": "narrator|lead_adult|child", "description": "..."}],\n'
        '  "beats": [\n'
        '    {"beat_number": 1, "character": "CharName", "dialogue": "Speech text", "visual_prompt": "Panel description", "camera_effect": "zoom_in"}\n'
        "  ]\n"
        "}\n"
        f"Language of dialogue: {lang.upper()}. Exactly 9 beats required."
    )
    user_prompt = f"Create a short {genre} story storyboard about: '{topic}'"
    
    story_data = call_ollama_json(user_prompt, system_prompt)
    beats = story_data.get("beats", [])
    if len(beats) < 9:
        print(f"[Engine] Beats count ({len(beats)}) < 9, padding default beats...")
        beats = generate_fallback_storyboard(topic)["beats"]

    # -------------------------------------------------------------------------
    # STEP B: Grid Image Generation & Splitting
    # -------------------------------------------------------------------------
    print("\n[Step B] Generating Consistent 3x3 Visual Grid Image...")
    grid_prompt = construct_nanobanana_grid_prompt(topic, genre, beats)
    grid_bytes = call_local_image_generator(grid_prompt, width=1536, height=1536)
    
    grid_image_path = temp_dir / "composite_grid.png"
    grid_image_path.write_bytes(grid_bytes)
    print(f"[Grid] Composite image saved to {grid_image_path}")

    print("\n[Step B.2] Splitting 3x3 Composite Grid into 9 Shot Frames...")
    shot_paths = split_grid(
        grid_image=grid_bytes,
        output_dir=temp_dir / "shots",
        rows=3,
        cols=3,
        output_format="png",
        prefix="shot_",
    )

    # -------------------------------------------------------------------------
    # STEP C: Multi-Voice Audio & SRT Subtitle Synthesis
    # -------------------------------------------------------------------------
    print("\n[Step C] Synthesizing Multi-Voice Audio & Subtitles via Edge-TTS...")
    voices = VOICE_PROFILES.get(lang, VOICE_PROFILES["fr"])
    scene_assets: List[SceneAsset] = []

    effects_cycle = ["zoom_in", "pan_right", "zoom_out", "pan_left"]

    for idx, beat in enumerate(beats[:9]):
        beat_num = idx + 1
        char_role = beat.get("character_role", "narrator")
        voice_id = voices.get(char_role, voices["narrator"])
        dialogue = beat.get("dialogue", f"Scène {beat_num}")
        
        mp3_path = temp_dir / f"audio_beat_{beat_num:02d}.mp3"
        srt_path = temp_dir / f"sub_beat_{beat_num:02d}.srt"
        
        duration = await synthesize_edge_tts(dialogue, voice_id, mp3_path)
        create_srt_file(dialogue, duration, srt_path)
        
        shot_img_path = str(shot_paths[idx]) if idx < len(shot_paths) else str(shot_paths[0])
        
        scene_assets.append(
            SceneAsset(
                scene_number=beat_num,
                image_path=shot_img_path,
                audio_path=str(mp3_path),
                subtitle_path=str(srt_path),
                duration_seconds=duration,
                narration_text=dialogue,
            )
        )
        print(f"   Beat {beat_num}/9: duration={duration:.2f}s | Voice={voice_id}")

    # -------------------------------------------------------------------------
    # STEP D: Final Video Assembly via VideoComposer
    # -------------------------------------------------------------------------
    print("\n[Step D] Assembling Final MP4 Video with Ken Burns Motion & Subtitles...")
    composer = VideoComposer(width=720, height=1280, fps=30)
    
    clean_title = re.sub(r"[^\w\-_]", "_", topic.lower())
    final_video_name = f"autonomous_drama_{clean_title}_{int(time.time())}.mp4"
    final_video_path = out_path / final_video_name

    result = await composer.compose_episode(
        scenes=scene_assets,
        output_path=str(final_video_path),
        title=topic,
    )

    if result.success and os.path.exists(final_video_path):
        print(f"\n==================================================")
        print(f"🎉 SUCCESS! Final Autonomous Video Rendered:")
        print(f"   📁 {final_video_path.resolve()}")
        print(f"   ⏱️ Duration: {result.duration_seconds:.2f}s")
        print(f"==================================================")
    else:
        print(f"\n❌ VIDEO ASSEMBLY FAILED: {result.error}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="DramaClaw Headless Autonomous Drama Engine")
    parser.add_argument("--topic", type=str, required=True, help="Topic or prompt for story generation")
    parser.add_argument("--genre", type=str, default="kids", choices=["kids", "drama"], help="Genre preset")
    parser.add_argument("--lang", type=str, default="fr", choices=["fr", "en"], help="Target audio/subtitle language")
    parser.add_argument("--output-dir", type=str, default="data/output", help="Directory for output video")

    args = parser.parse_args()
    asyncio.run(run_autonomous_pipeline(args.topic, args.genre, args.lang, args.output_dir))


if __name__ == "__main__":
    main()

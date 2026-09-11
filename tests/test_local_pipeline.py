"""Local Pipeline End-to-End Smoke Test.

Validates the complete DramaClaw local generation pipeline:
1. Storyboard Script (3-beat narrative)
2. Audio & Subtitles (Edge-TTS generator with .mp3 and .srt output, plus offline fallback)
3. Visuals (MockImageGenerator storyboard frames)
4. Video Composition (VideoComposer FFmpeg scene stitching, subtitles burn-in, and final .mp4 validation)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from novelvideo.egress_context import TrustedEgressContext
from novelvideo.generators.image_generator import MockImageGenerator
from novelvideo.generators.tts_generator import EdgeTTSGenerator, TTSResult
from novelvideo.generators.video_composer import SceneAsset, VideoComposer, VideoResult
from novelvideo.ports import registry
from novelvideo.ports.authz import BillingPrincipal
from novelvideo.ports.egress_operations import (
    OperationClaimResult,
    OperationSnapshot,
    OperationState,
)
from novelvideo.ports.model_credentials import CredentialReference


class _LocalOperationPort:
    """Lightweight in-memory EgressOperationPort for local CE testing."""

    def __init__(self) -> None:
        self.operations: dict[str, OperationSnapshot] = {}

    async def claim(self, *, spec: Any) -> OperationClaimResult:
        op = OperationSnapshot(
            operation_id="local-op-1",
            operation_key=spec.operation_key,
            state=OperationState.DISPATCHING,
            version=1,
        )
        return OperationClaimResult(won=True, operation=op, transition_token="local-token")

    async def mark_accepted(self, **kwargs: Any) -> OperationSnapshot:
        return OperationSnapshot(
            operation_id="local-op-1",
            operation_key="local-key",
            state=OperationState.ACCEPTED,
            version=2,
        )

    async def mark_completed(self, **kwargs: Any) -> OperationSnapshot:
        return OperationSnapshot(
            operation_id="local-op-1",
            operation_key="local-key",
            state=OperationState.COMPLETED,
            version=3,
        )

    async def mark_rejected_before_submit(self, **kwargs: Any) -> OperationSnapshot:
        return OperationSnapshot(
            operation_id="local-op-1",
            operation_key="local-key",
            state=OperationState.REJECTED_BEFORE_SUBMIT,
            version=2,
        )

    async def mark_unknown(self, **kwargs: Any) -> OperationSnapshot:
        return OperationSnapshot(
            operation_id="local-op-1",
            operation_key="local-key",
            state=OperationState.UNKNOWN,
            version=2,
        )


def _create_local_test_context() -> TrustedEgressContext:
    """Create a valid local TrustedEgressContext for EdgeTTS."""
    return TrustedEgressContext(
        envelope_id="test-envelope-local",
        project_id="test-project-local",
        task_type="local_pipeline_test",
        requester_user_id="local-user",
        root_task_id="test-root-task",
        admission_id="test-admission",
        admitted_at=datetime.now(timezone.utc).isoformat(),
        membership_id=None,
        authz_version=1,
        billing_principal=BillingPrincipal(kind="local", id="local-user"),
        credential=CredentialReference(
            source="local",
            credential_id="local-test-cred",
            key_version=1,
        ),
    )


def _generate_fallback_audio(text: str, audio_path: str, duration_sec: float = 2.0) -> Tuple[str, str]:
    """Synthesize a clean silent MP3 and matching SRT subtitle using FFmpeg for air-gapped fallback."""
    os.makedirs(os.path.dirname(audio_path), exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=stereo:d={duration_sec}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            audio_path,
        ],
        check=True,
        capture_output=True,
    )

    srt_path = audio_path.rsplit(".", 1)[0] + ".srt"
    ms_end = int(duration_sec * 1000)
    sec_end = ms_end // 1000
    rem_ms = ms_end % 1000

    srt_content = (
        f"1\n"
        f"00:00:00,000 --> 00:00:{sec_end:02d},{rem_ms:03d}\n"
        f"{text}\n\n"
    )
    Path(srt_path).write_text(srt_content, encoding="utf-8")
    return audio_path, srt_path


@pytest.fixture
def local_ports_setup():
    """Ensure in-memory egress_operations port is registered during test."""
    original_port = registry._PORTS.get("egress_operations")
    registry._PORTS["egress_operations"] = _LocalOperationPort()
    yield
    if original_port is not None:
        registry._PORTS["egress_operations"] = original_port
    else:
        registry._PORTS.pop("egress_operations", None)


@pytest.mark.asyncio
async def test_local_pipeline_storyboard_to_video(tmp_path: Path, local_ports_setup) -> None:
    """Execute end-to-end 3-beat storyboard generation, TTS audio, visuals, and video stitching."""
    # 1. Define 3-beat drama test script
    storyboard_beats = [
        {
            "beat_number": 1,
            "title": "踏入森林",
            "narration": "小明踏入了一片充满迷雾的古老森林，周围异常安静。",
            "visual_prompt": "Young explorer walking into a mysterious misty forest, cinematic lighting, photorealistic 8k",
        },
        {
            "beat_number": 2,
            "title": "神秘金光",
            "narration": "微风吹过，前方的灌木丛中忽然泛起奇异的金色光芒。",
            "visual_prompt": "Golden glowing mystical light beaming through dense dark forest bushes, volumetric god rays",
        },
        {
            "beat_number": 3,
            "title": "魔法古书",
            "narration": "他快步上前查看，在石台之上赫然躺着一本失落已久的魔法典籍。",
            "visual_prompt": "Ancient weathered leather spellbook glowing with magical runes on stone altar, high detail",
        },
    ]

    images_dir = tmp_path / "images"
    audio_dir = tmp_path / "audio"
    output_dir = tmp_path / "output"
    images_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. Visuals: Generate storyboard frames using MockImageGenerator
    img_gen = MockImageGenerator()
    image_paths: list[str] = []
    for beat in storyboard_beats:
        img_file = str(images_dir / f"beat_{beat['beat_number']:02d}.png")
        res = await img_gen.generate(
            prompt=beat["visual_prompt"],
            output_path=img_file,
            width=720,
            height=1280,
        )
        assert res.success is True, f"Failed to generate frame for beat {beat['beat_number']}"
        assert os.path.isfile(img_file), f"Frame {img_file} not found"
        assert os.path.getsize(img_file) > 0

        # Verify image format and geometry with PIL
        with Image.open(img_file) as img:
            assert img.size == (720, 1280)
            assert img.format == "PNG"

        image_paths.append(img_file)

    # 3. Audio & Subtitles: Generate with EdgeTTS (or graceful offline fallback)
    egress_ctx = _create_local_test_context()
    tts_gen = EdgeTTSGenerator(voice="zh-CN-YunxiNeural", egress_context=egress_ctx)

    scene_assets: list[SceneAsset] = []

    for i, beat in enumerate(storyboard_beats):
        audio_file = str(audio_dir / f"beat_{beat['beat_number']:02d}.mp3")
        tts_result: TTSResult

        try:
            tts_result = await tts_gen.generate(
                text=beat["narration"],
                output_path=audio_file,
                generate_subtitle=True,
            )
            # Check if synthesis returned valid audio
            if not tts_result.success or not os.path.isfile(audio_file) or os.path.getsize(audio_file) == 0:
                raise RuntimeError(f"EdgeTTS failed or returned empty: {tts_result.error}")
        except Exception as e:
            # Resilient fallback if edge-tts endpoint is blocked or offline
            print(f"[Notice] EdgeTTS offline/unavailable, using synthetic fallback: {e}")
            a_path, s_path = _generate_fallback_audio(beat["narration"], audio_file, duration_sec=2.0)
            tts_result = TTSResult(
                success=True,
                audio_path=a_path,
                subtitle_path=s_path,
                duration_seconds=2.0,
            )

        assert tts_result.success is True
        assert tts_result.audio_path is not None and os.path.isfile(tts_result.audio_path)
        assert os.path.getsize(tts_result.audio_path) > 0

        # Subtitles verification
        assert tts_result.subtitle_path is not None and os.path.isfile(tts_result.subtitle_path)
        srt_text = Path(tts_result.subtitle_path).read_text(encoding="utf-8")
        assert "-->" in srt_text, "Subtitle file does not contain valid SRT timestamps"

        scene_assets.append(
            SceneAsset(
                scene_number=beat["beat_number"],
                image_path=image_paths[i],
                audio_path=tts_result.audio_path,
                subtitle_path=tts_result.subtitle_path,
                duration_seconds=tts_result.duration_seconds or 2.0,
                narration_text=beat["narration"],
            )
        )

    assert len(scene_assets) == 3

    # 4. Video Assembly: Compose scenes into single .mp4 using VideoComposer
    composer = VideoComposer()
    composer.width = 720
    composer.height = 1280

    composed_video_path = str(output_dir / "composed_story.mp4")
    compose_result: VideoResult = await composer.compose_episode(
        scenes=scene_assets,
        output_path=composed_video_path,
        title="测试短剧：森林秘境",
        add_title_card=False,
        add_end_card=False,
        ken_burns=False,
    )

    assert compose_result.success is True, f"Video composition failed: {compose_result.error}"
    assert os.path.isfile(composed_video_path)
    assert os.path.getsize(composed_video_path) > 1024, "Video output size unexpectedly small"

    # 5. Burn-in Subtitles
    # Combine individual scene subtitles into a master subtitle track
    master_srt_path = str(output_dir / "master_subtitles.srt")
    current_offset_sec = 0.0
    master_srt_entries: list[str] = []
    entry_index = 1

    for asset in scene_assets:
        dur = asset.duration_seconds
        start_sec = current_offset_sec
        end_sec = current_offset_sec + dur

        start_s = int(start_sec)
        start_ms = int((start_sec - start_s) * 1000)
        end_s = int(end_sec)
        end_ms = int((end_sec - end_s) * 1000)

        entry = (
            f"{entry_index}\n"
            f"00:00:{start_s:02d},{start_ms:03d} --> 00:00:{end_s:02d},{end_ms:03d}\n"
            f"{asset.narration_text}\n"
        )
        master_srt_entries.append(entry)
        current_offset_sec += dur
        entry_index += 1

    Path(master_srt_path).write_text("\n".join(master_srt_entries), encoding="utf-8")

    subtitled_video_path = str(output_dir / "final_subtitled_story.mp4")
    sub_result = await composer.add_subtitles(
        video_path=composed_video_path,
        subtitle_path=master_srt_path,
        output_path=subtitled_video_path,
    )

    assert sub_result.success is True, f"Subtitles burn-in failed: {sub_result.error}"
    assert os.path.isfile(subtitled_video_path)
    assert os.path.getsize(subtitled_video_path) > 1024

    # 6. Verify with FFprobe that final .mp4 is valid and has both video and audio streams
    probe_res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-of",
            "csv=p=0",
            subtitled_video_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    probe_output = probe_res.stdout.lower()
    assert "video" in probe_output, "No video stream detected in output mp4"
    assert "audio" in probe_output, "No audio stream detected in output mp4"


@pytest.mark.asyncio
async def test_mock_image_generator_features(tmp_path: Path) -> None:
    """Verify MockImageGenerator creates valid images with correct dimensions."""
    gen = MockImageGenerator()
    out_file = str(tmp_path / "mock_test.png")
    result = await gen.generate(
        prompt="A cute cat exploring a garden",
        output_path=out_file,
        width=1080,
        height=1920,
    )

    assert result.success is True
    assert os.path.isfile(out_file)
    with Image.open(out_file) as img:
        assert img.size == (1080, 1920)
        assert img.mode == "RGB"

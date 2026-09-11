# DramaClaw: Windows Bare-Metal Local Run Guide (100% Free Engines)

This guide details how to run DramaClaw directly on Windows bare-metal without Docker and without paying for external cloud APIs.

---

## 1. Prerequisites

1. **Python 3.11 Conda Environment**:
   - Environment Name: `dramaclaw_env`
   - Location: `C:\Users\ansel\miniconda3\envs\dramaclaw_env`
   - Python Version: `3.11.16` (Note: Python 3.10 is not supported due to dependency constraints)

2. **FFmpeg & FFprobe**:
   - Must be accessible in system PATH.
   - Verified installation: `ffmpeg version 8.1.1` (Gyan build).
   - If not installed:
     ```powershell
     winget install Gyan.FFmpeg
     ```

3. **Node.js & pnpm** (for Frontend UI):
   - Node.js 20+ / 22+
   - pnpm: `npm install -g pnpm` or `corepack enable`

4. **Local Model Engines ($0 Cost)**:
   - **Ollama**: Running locally on `http://localhost:11434` with `qwen2.5:14b-instruct` or `qwen2.5:7b-instruct`:
     ```powershell
     ollama run qwen2.5:14b-instruct
     ```
   - **Edge-TTS**: Built-in Microsoft Edge speech synthesis (zero API keys, automatic `.srt` subtitles).
   - **ComfyUI** (Optional, for local video generation): Running on `http://127.0.0.1:8188` with Wan 2.2 GGUF models.

---

## 2. Environment Configuration (`.env`)

A local `.env` file has been pre-configured in the repository root (`C:\Users\ansel\Documents\dramaclaw\.env`):

```ini
# Edition & Process Management
ST_EDITION=ce
ST_CONTROL_PLANE_DSN=
ST_REDIS_URL=
ST_CELERY_BROKER_URL=

# Local Storage Paths (Bare-Metal)
NOVELVIDEO_DATA_ROOT=./data
NOVELVIDEO_OUTPUT_DIR=./data/output
NOVELVIDEO_STATE_DIR=./data/state
NOVELVIDEO_RUNTIME_DIR=./data/runtime

# Local OpenAI-Compatible LLM Gateway (Ollama)
NEWAPI_BASE_URL=http://localhost:11434/v1
NEWAPI_API_KEY=ollama
BASE_URL=http://localhost:11434/v1
API_KEY=ollama
MODEL_PROVIDER=openai
MODEL_BASE_URL=http://localhost:11434/v1
MODEL_API_KEY=ollama
MODEL_NAME=qwen2.5:14b-instruct
DEFAULT_TEXT_MODEL=qwen2.5:14b-instruct

# Audio & Speech (Free Edge-TTS with native subtitles)
TTS_PROVIDER=edge
EDGE_TTS_VOICE=zh-CN-YunxiNeural
DEFAULT_VOICE=zh-CN-YunxiNeural

# Local ComfyUI Video Generation
COMFYUI_ADDRESS=127.0.0.1:8188
COMFYUI_USE_SSL=false
VIDEO_BACKEND=comfyui
COMFYUI_WORKFLOW=gguf

# Security
PROMPT_EXPORT_PASSWORD=local_dramaclaw_dev_pass_2026
NEWAPI_PROVISIONER_ENABLED=false
RELEASE_NOTIFICATIONS_ENABLED=false
```

---

## 3. Single-Command Headless Runner (`run_local.py`)

DramaClaw includes a dedicated headless local launcher that automates pre-flight health checks and concurrently spawns both the backend REST API and the frontend UI in a single command with graceful shutdown:

```powershell
# Run from the repository root:
conda run -n dramaclaw_env python run_local.py
```

### Launcher Features & Options:
- **Pre-flight Health Checks**: Verifies Ollama, ComfyUI, FFmpeg, Python version (>= 3.11), and port availability before launching.
- **Graceful Shutdown**: Pressing `Ctrl+C` cleanly terminates all child process trees (node, vite, python, uvicorn) without leaving orphan background processes.
- **Command Line Flags**:
  - `python run_local.py --check-only`: Perform pre-flight service reachability checks and exit without starting servers.
  - `python run_local.py --serve-dist`: Serve pre-built `frontend/dist` static assets instead of the Vite dev server.
  - `python run_local.py --backend-port 8780`: Custom backend REST API port.
  - `python run_local.py --frontend-port 8080`: Custom frontend UI port.
  - `python run_local.py --backend-only` / `--frontend-only`: Launch only one service tier.

---

## 4. Manual Multi-Terminal Execution (Alternative)

If you prefer to run services in separate terminals:

### Terminal 1: Backend API
```powershell
conda run -n dramaclaw_env python -m novelvideo.cli api --port 8780
```
> Verify at [http://localhost:8780/api/v1/config](http://localhost:8780/api/v1/config) or OpenAPI docs at [http://localhost:8780/docs](http://localhost:8780/docs).

### Terminal 2: Frontend UI
```powershell
cd frontend
pnpm dev --port 8080
```
> Open [http://localhost:8080](http://localhost:8080) in your web browser.

---

## 5. End-to-End Local Pipeline Smoke Test

An automated regression smoke test validates the full DramaClaw pipeline end-to-end without external cloud dependencies:
- **Storyboard Generation**: 3-beat narrative script.
- **Audio & Subtitles**: Live Edge-TTS synthesis generating `.mp3` audio and synchronized `.srt` subtitles.
- **Visuals**: Storyboard frame synthesis with Pillow / MockImageGenerator.
- **Mastering**: Video assembly, Ken Burns effect scaling, subtitle burn-in, and FFmpeg/ffprobe validation.

Execute the smoke test:
```powershell
conda run -n dramaclaw_env python -m pytest tests/test_local_pipeline.py -v
```

---

## 6. How the 100% Free Local Pipeline Operates

| Pipeline Stage | Engine Invoked | Cost | VRAM Footprint |
|---|---|---|---|
| **Novel Ingest & Character Extraction** | Local Ollama (`qwen2.5:14b-instruct`) | $0 | ~9 GB VRAM |
| **Visual Beat Planning** | Local Ollama (`qwen2.5:14b-instruct`) | $0 | ~9 GB VRAM |
| **Dialogue & Narration Audio** | Microsoft Edge-TTS (`zh-CN-YunxiNeural`) | $0 | 0 MB (Network streaming) |
| **Subtitle Timestamps** | Built-in `edge_tts.SubMaker` (`.srt`) | $0 | 0 MB (CPU) |
| **Storyboard Panel Slicing** | Native NumPy/Pillow (`grid_splitter.py`) | $0 | 0 MB (CPU) |
| **Shot Video Motion (I2V)** | Local ComfyUI (`wan2.2-i2v-gguf-LightX2V`) | $0 | ~8–14 GB VRAM |
| **Episode Stitching & Mastering** | Native FFmpeg subprocesses (`video_composer.py`) | $0 | 0 MB (CPU) |

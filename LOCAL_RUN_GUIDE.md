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

## 3. Starting the Backend API

Open a PowerShell terminal and run:

```powershell
# 1. Navigate to repository root
cd C:\Users\ansel\Documents\dramaclaw

# 2. Activate Conda Environment
conda activate dramaclaw_env

# 3. Start the FastAPI REST server on port 8780
python -m novelvideo.cli api --port 8780
```

> **API Health Check**: Once started, verify at [http://localhost:8780/api/v1/config](http://localhost:8780/api/v1/config) or view interactive OpenAPI docs at [http://localhost:8780/docs](http://localhost:8780/docs).

---

## 4. Starting the Frontend UI

Open a second PowerShell terminal:

```powershell
# 1. Navigate to frontend directory
cd C:\Users\ansel\Documents\dramaclaw\frontend

# 2. Install frontend dependencies (if not already installed)
pnpm install

# 3. Start the Vite development server on port 8080
pnpm dev --port 8080
```

> **UI Access**: Open [http://localhost:8080](http://localhost:8080) in your web browser. The frontend automatically reverse-proxies `/api` and `/static` requests to the backend on port 8780.

---

## 5. Sanity Check & Verification Commands

To verify that the environment and backend components are correctly wired:

1. **CLI Help Check**:
   ```powershell
   conda run -n dramaclaw_env python -m novelvideo.cli --help
   ```

2. **Backend Application Initialization Test**:
   ```powershell
   conda run -n dramaclaw_env python -c "from novelvideo.app import app; print('DramaClaw backend loaded successfully!')"
   ```

3. **FFmpeg Subprocess Check**:
   ```powershell
   ffmpeg -version
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

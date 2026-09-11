#!/usr/bin/env python3
"""DramaClaw / NovelVideo Headless Local Runner.

Orchestrates local services (Backend API + Frontend Dev Server)
with pre-flight health checks for Ollama, ComfyUI, FFmpeg, and .env configuration.
Handles graceful shutdown of process trees on Windows.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Configure line buffering and UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
os.environ["PYTHONUNBUFFERED"] = "1"

# Enable VT100 escape sequences on Windows consoles if available
if sys.platform == "win32":
    os.system("")

# ANSI styling
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

REPO_ROOT = Path(__file__).resolve().parent
ENV_FILE = REPO_ROOT / ".env"
FRONTEND_DIR = REPO_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

# Active child processes to terminate on exit
ACTIVE_PROCESSES: List[subprocess.Popen] = []
SHUTTING_DOWN = False


def log_info(msg: str) -> None:
    print(f"{BLUE}[INFO]{RESET} {msg}")


def log_ok(msg: str) -> None:
    print(f"{GREEN}[✓]{RESET} {msg}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[!]{RESET} {msg}")


def log_error(msg: str) -> None:
    print(f"{RED}[✗]{RESET} {msg}")


def load_env_vars() -> Dict[str, str]:
    """Parse .env file into a dictionary without requiring external packages."""
    env_vars: Dict[str, str] = {}
    if not ENV_FILE.is_file():
        return env_vars

    with open(ENV_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, val = stripped.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                env_vars[key] = val
                if key not in os.environ:
                    os.environ[key] = val
    return env_vars


def find_python_executable() -> str:
    """Detect the appropriate Python interpreter with dependencies."""
    candidates = [
        # 1. Current sys.executable if it has novelvideo
        sys.executable,
        # 2. Local project .venv
        str(REPO_ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")),
        # 3. User miniconda dramaclaw_env
        str(Path.home() / "miniconda3" / "envs" / "dramaclaw_env" / ("python.exe" if sys.platform == "win32" else "bin/python")),
    ]

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                res = subprocess.run(
                    [candidate, "-c", "import novelvideo; print('ok')"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if res.returncode == 0 and "ok" in res.stdout:
                    return candidate
            except Exception:
                continue

    # Fallback to sys.executable
    return sys.executable


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a network port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_ffmpeg() -> Tuple[bool, str]:
    """Verify FFmpeg availability on PATH."""
    try:
        res = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0 and res.stdout:
            first_line = res.stdout.splitlines()[0]
            return True, first_line
    except Exception as e:
        return False, str(e)
    return False, "ffmpeg not found in PATH"


def check_ollama(base_url: str) -> Tuple[bool, str]:
    """Check if Ollama is online and list pulled models."""
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]

    tags_endpoint = f"{url}/api/tags"
    try:
        req = urllib.request.Request(
            tags_endpoint,
            headers={"User-Agent": "DramaClaw-HealthCheck"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                if models:
                    model_summary = f"{len(models)} models available: {', '.join(models[:3])}"
                    if len(models) > 3:
                        model_summary += f", +{len(models) - 3} more"
                    return True, model_summary
                return True, "Online (No models pulled yet)"
    except Exception as e:
        return False, str(e)
    return False, "Connection failed"


def check_comfyui(address: str) -> Tuple[bool, str]:
    """Check if ComfyUI service is responding."""
    url = address if address.startswith("http") else f"http://{address}"
    stats_endpoint = f"{url.rstrip('/')}/system_stats"
    try:
        req = urllib.request.Request(
            stats_endpoint,
            headers={"User-Agent": "DramaClaw-HealthCheck"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                return True, "Online (Ready for video/image generation)"
    except Exception as e:
        return False, str(e)
    return False, "Connection failed"


def terminate_process_tree(proc: subprocess.Popen) -> None:
    """Cleanly terminate a process and all its child processes."""
    if proc.poll() is not None:
        return

    pid = proc.pid
    if sys.platform == "win32":
        try:
            # Forcefully terminate entire process tree on Windows
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            proc.terminate()

    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()


def shutdown(signum=None, frame=None) -> None:
    """Global shutdown handler."""
    global SHUTTING_DOWN
    if SHUTTING_DOWN:
        return
    SHUTTING_DOWN = True

    print(f"\n{YELLOW}[SHUTDOWN]{RESET} Stopping DramaClaw services gracefully...")
    for proc in ACTIVE_PROCESSES:
        terminate_process_tree(proc)
    print(f"{GREEN}[✓]{RESET} All processes stopped. Goodbye!\n")
    sys.exit(0)


def stream_logs(pipe, prefix: str, color_code: str) -> None:
    """Stream subprocess logs with styled prefix."""
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            line_str = line.rstrip()
            if line_str:
                print(f"{color_code}[{prefix}]{RESET} {line_str}", flush=True)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def print_banner() -> None:
    banner = f"""{CYAN}{BOLD}
    ===============================================================
                       D R A M A C L A W
             Bare-Metal Local Headless Orchestrator
    ===============================================================
    {RESET}"""
    print(banner)


def run_preflight_checks(env_vars: Dict[str, str], backend_port: int, frontend_port: int) -> bool:
    """Execute all pre-flight service checks."""
    print(f"{BOLD}--- [1/3] System & Environment Health Checks ---{RESET}")

    # Python Version
    py_ver = platform.python_version()
    if sys.version_info < (3, 11):
        log_error(f"Python >= 3.11 required (current: {py_ver})")
        return False
    else:
        log_ok(f"Python Runtime: {py_ver} ({sys.executable})")

    # .env File
    if ENV_FILE.is_file():
        log_ok(f"Configuration: Loaded .env ({len(env_vars)} variables)")
    else:
        log_warn("No .env found at repository root. Using system defaults / fallback.")
        log_info("Tip: run 'copy .env.example .env' to customize local configuration.")

    # Print Key Config Values
    edition = env_vars.get("ST_EDITION", "ce")
    model_name = env_vars.get("MODEL_NAME", "qwen2.5:14b-instruct")
    tts_provider = env_vars.get("TTS_PROVIDER", "edge")
    tts_voice = env_vars.get("EDGE_TTS_VOICE", "zh-CN-YunxiNeural")
    video_backend = env_vars.get("VIDEO_BACKEND", "comfyui")
    image_model = env_vars.get("NEWAPI_IMAGE_MODEL", "sdxl-turbo")

    print(f"    - Edition:        {CYAN}{edition.upper()}{RESET}")
    print(f"    - Text LLM:       {CYAN}{model_name}{RESET}")
    print(f"    - Audio TTS:      {CYAN}{tts_provider} ({tts_voice}){RESET}")
    print(f"    - Image Engine:   {CYAN}{image_model}{RESET}")
    print(f"    - Video Engine:   {CYAN}{video_backend}{RESET}")

    print(f"\n{BOLD}--- [2/3] Service Reachability Checks ---{RESET}")

    # FFmpeg check
    ff_ok, ff_info = check_ffmpeg()
    if ff_ok:
        log_ok(f"FFmpeg Engine: {ff_info}")
    else:
        log_error(f"FFmpeg is missing: {ff_info}")
        log_warn("Install FFmpeg (e.g. via 'winget install Gyan.FFmpeg') and ensure ffmpeg is in PATH.")

    # Ollama check
    ollama_url = env_vars.get("NEWAPI_BASE_URL", "http://localhost:11434/v1")
    ollama_ok, ollama_info = check_ollama(ollama_url)
    if ollama_ok:
        log_ok(f"Ollama LLM Gateway ({ollama_url}): {ollama_info}")
    else:
        log_warn(f"Ollama is offline or unreachable at {ollama_url}")
        print(f"    {YELLOW}↳ Action required if using local LLM:{RESET}")
        print(f"      1. Start Ollama in a separate terminal: {BOLD}ollama serve{RESET}")
        print(f"      2. Pull model if needed: {BOLD}ollama pull {model_name}{RESET}")

    # ComfyUI check
    comfyui_addr = env_vars.get("COMFYUI_ADDRESS", "127.0.0.1:8188")
    comfy_ok, comfy_info = check_comfyui(comfyui_addr)
    if comfy_ok:
        log_ok(f"ComfyUI Generator ({comfyui_addr}): {comfy_info}")
    else:
        log_warn(f"ComfyUI is not detected on {comfyui_addr}")
        print(f"    {DIM}↳ Notice: ComfyUI is needed only when generating local AI video (Wan2.2/LTX).{RESET}")

    # Port checks
    if is_port_in_use(backend_port):
        log_warn(f"Backend port {backend_port} is currently IN USE!")
    else:
        log_ok(f"Backend port {backend_port} is available.")

    if is_port_in_use(frontend_port):
        log_warn(f"Frontend port {frontend_port} is currently IN USE!")
    else:
        log_ok(f"Frontend port {frontend_port} is available.")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DramaClaw Headless Single-Command Local Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--backend-port", type=int, default=8780, help="Backend REST API port")
    parser.add_argument("--frontend-port", type=int, default=8080, help="Frontend UI port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host bind address")
    parser.add_argument("--check-only", action="store_true", help="Run pre-flight health checks and exit")
    parser.add_argument("--serve-dist", action="store_true", help="Serve built frontend/dist instead of Vite dev server")
    parser.add_argument("--backend-only", action="store_true", help="Start only backend API server")
    parser.add_argument("--frontend-only", action="store_true", help="Start only frontend dev server")
    args = parser.parse_args()

    # Register termination signals
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print_banner()
    env_vars = load_env_vars()
    run_preflight_checks(env_vars, args.backend_port, args.frontend_port)

    if args.check_only:
        print(f"\n{GREEN}[✓]{RESET} Pre-flight checks completed.")
        return

    print(f"\n{BOLD}--- [3/3] Launching Local DramaClaw Services ---{RESET}")

    python_exe = find_python_executable()
    log_info(f"Using Python: {python_exe}")

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    # 1. Spawn Backend API Server
    if not args.frontend_only:
        backend_cmd = [
            python_exe,
            "-m",
            "novelvideo.cli",
            "api",
            "--port",
            str(args.backend_port),
            "--host",
            args.host,
        ]
        log_info(f"Starting Backend API on http://{args.host}:{args.backend_port} ...")
        backend_proc = subprocess.Popen(
            backend_cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        ACTIVE_PROCESSES.append(backend_proc)

        t_backend = threading.Thread(
            target=stream_logs,
            args=(backend_proc.stdout, "BACKEND", BLUE),
            daemon=True,
        )
        t_backend.start()

    # 2. Spawn Frontend
    if not args.backend_only:
        if args.serve_dist:
            if not FRONTEND_DIST.is_dir():
                log_error(f"frontend/dist directory does not exist. Run 'pnpm run build' inside frontend/ first.")
                shutdown()
            log_info(f"Serving built frontend static files on http://{args.host}:{args.frontend_port} ...")
            frontend_cmd = [
                python_exe,
                "-m",
                "http.server",
                str(args.frontend_port),
                "--bind",
                args.host,
                "--directory",
                str(FRONTEND_DIST),
            ]
            frontend_cwd = str(REPO_ROOT)
        else:
            log_info(f"Starting Vite Dev Server on http://{args.host}:{args.frontend_port} ...")
            # Set VITE_API_URL so the proxy targets our backend
            os.environ["VITE_API_URL"] = f"http://{args.host}:{args.backend_port}"
            pnpm_cmd = "pnpm.cmd" if sys.platform == "win32" else "pnpm"
            frontend_cmd = [
                pnpm_cmd,
                "run",
                "dev",
                "--port",
                str(args.frontend_port),
                "--host",
                args.host,
            ]
            frontend_cwd = str(FRONTEND_DIR)

        frontend_proc = subprocess.Popen(
            frontend_cmd,
            cwd=frontend_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        ACTIVE_PROCESSES.append(frontend_proc)

        t_frontend = threading.Thread(
            target=stream_logs,
            args=(frontend_proc.stdout, "FRONTEND", CYAN),
            daemon=True,
        )
        t_frontend.start()

    print(f"\n{GREEN}{BOLD}DramaClaw is running!{RESET}")
    print(f"  • Frontend UI:  {CYAN}http://{args.host}:{args.frontend_port}{RESET}")
    print(f"  • REST API:     {CYAN}http://{args.host}:{args.backend_port}/api/v1{RESET}")
    print(f"  • API Docs:     {CYAN}http://{args.host}:{args.backend_port}/docs{RESET}")
    print(f"\nPress {YELLOW}Ctrl+C{RESET} at any time to shut down all processes cleanly.\n")

    try:
        while True:
            for p in ACTIVE_PROCESSES:
                ret = p.poll()
                if ret is not None:
                    log_warn(f"Process (PID {p.pid}) exited unexpectedly with code {ret}")
                    shutdown()
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()

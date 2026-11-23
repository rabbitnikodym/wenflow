"""Runtime configuration, loaded from the repo-level .env file."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("WENFLOW_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
MEDIA_DIR = DATA_DIR / "media"
CONTENT_DIR = Path(__file__).resolve().parent / "content"
WEB_DIST = ROOT / "web" / "dist"

for d in (DATA_DIR, RAW_DIR, MEDIA_DIR):
    d.mkdir(parents=True, exist_ok=True)

DICT_DB = DATA_DIR / "dict.sqlite"
APP_DB = DATA_DIR / "app.sqlite"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Main model for lessons, tutoring and feedback. Fast model for quick glosses.
LLM_MODEL = os.getenv("WENFLOW_LLM_MODEL", "gpt-6.2-sol")
LLM_FAST_MODEL = os.getenv("WENFLOW_LLM_FAST_MODEL", "gpt-6.2-sol")
OPENAI_TRANSCRIBE_MODEL = os.getenv("WENFLOW_TRANSCRIBE_MODEL", "gpt-4o-transcribe")

# Local speech recognition (faster-whisper). "auto" tries CUDA then falls back to CPU.
WHISPER_MODEL = os.getenv("WENFLOW_WHISPER_MODEL", "large-v3-turbo")
WHISPER_DEVICE = os.getenv("WENFLOW_WHISPER_DEVICE", "auto")

# Text-to-speech: "edge" (Microsoft neural zh-TW voices), "openai", or "browser".
TTS_ENGINE = os.getenv("WENFLOW_TTS_ENGINE", "edge")
TTS_VOICE = os.getenv("WENFLOW_TTS_VOICE", "zh-TW-HsiaoChenNeural")

# The learner's study start date. Day 1 of the curriculum is this date.
START_DATE = os.getenv("WENFLOW_START_DATE", "")

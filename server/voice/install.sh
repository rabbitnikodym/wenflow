#!/usr/bin/env bash
# Install the local Taiwanese voice (BreezyVoice) into data/voice/, separate from the app's environment.
#   server/voice/install.sh
# Needs about 8 GB of disk and an NVIDIA GPU (it also runs on CPU, slowly).
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/bin:$PATH"
VOICE=data/voice
mkdir -p "$VOICE"

if [ ! -d "$VOICE/BreezyVoice/.git" ]; then
  git clone --depth 1 https://github.com/mtkresearch/BreezyVoice.git "$VOICE/BreezyVoice"
fi
if [ ! -x "$VOICE/venv/bin/python" ]; then
  uv venv --python 3.10 "$VOICE/venv"
fi
uv pip install --python "$VOICE/venv/bin/python" --index-strategy unsafe-best-match -r server/voice/requirements.txt
"$VOICE/venv/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
print("model at", snapshot_download("MediaTek-Research/BreezyVoice-300M"))
PY
echo "Installed. The app starts the voice worker by itself when the voice is selected in Settings."

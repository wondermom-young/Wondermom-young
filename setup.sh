#!/usr/bin/env bash
# 릴스 자동 편집 시스템 설치 (여러 번 실행해도 안전)
# 필요한 것: 파이썬 3.11 이상, Node.js, ffmpeg, Pretendard 글꼴, 브라우저(Playwright), 받아쓰기 모델
set -e
cd "$(dirname "$0")"
WORK="$(pwd)"

say() { printf '\n▶ %s\n' "$1"; }

# 1) 파이썬 3.11 이상
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then PY="$(command -v $c)"; break; fi
done
if [ -z "$PY" ]; then
  say "파이썬 3.11 설치"
  if command -v apt-get >/dev/null; then sudo apt-get update -y && sudo apt-get install -y python3.11 python3.11-venv; PY=/usr/bin/python3.11
  elif command -v brew >/dev/null; then brew install python@3.11; PY="$(brew --prefix)/bin/python3.11"
  else echo "파이썬 3.11을 설치할 수 없어요. https://www.python.org/downloads/ 에서 설치해 주세요."; exit 1; fi
fi
# faster-whisper 는 3.11/3.12 가 가장 안정적
for c in python3.11 python3.12; do command -v $c >/dev/null 2>&1 && PY="$(command -v $c)" && break; done
echo "파이썬: $PY"

# 2) ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  say "ffmpeg 설치"
  if command -v apt-get >/dev/null; then sudo apt-get install -y ffmpeg
  elif command -v brew >/dev/null; then brew install ffmpeg
  else echo "ffmpeg 를 설치할 수 없어요."; exit 1; fi
fi

# 3) Node.js
NODE="$(command -v node || true)"
[ -z "$NODE" ] && [ -x /opt/node22/bin/node ] && export PATH="/opt/node22/bin:$PATH" && NODE=/opt/node22/bin/node
if [ -z "$NODE" ]; then
  say "Node.js 설치"
  if command -v apt-get >/dev/null; then sudo apt-get install -y nodejs npm
  elif command -v brew >/dev/null; then brew install node
  else echo "Node.js 를 설치할 수 없어요. https://nodejs.org 에서 설치해 주세요."; exit 1; fi
fi

# 4) 파이썬 패키지 (.venv 안에)
if [ ! -x .venv/bin/python ]; then say "파이썬 가상환경(.venv) 만들기"; "$PY" -m venv .venv; fi
.venv/bin/python -c 'import faster_whisper, cv2, pyloudnorm, soundfile, scipy' 2>/dev/null || {
  say "파이썬 패키지 설치"
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r engine/requirements.txt
}

# 5) GSAP, Pretendard, Playwright
cd engine
[ -f node_modules/gsap/dist/gsap.min.js ] && [ -d node_modules/pretendard ] || { say "GSAP·Pretendard 받기"; npm install --silent; }
node -e "require('playwright')" 2>/dev/null || { say "Playwright 설치"; npm install --silent playwright@1 && npx playwright install chromium; }
cd "$WORK"
mkdir -p fonts
for w in ExtraBold Black Bold; do
  [ -f "fonts/Pretendard-$w.otf" ] || cp "engine/node_modules/pretendard/dist/public/static/Pretendard-$w.otf" fonts/
done
# 시스템 글꼴에도 등록 (자막 엔진용)
FD="$HOME/.fonts"; [ "$(uname)" = "Darwin" ] && FD="$HOME/Library/Fonts"
mkdir -p "$FD"; cp -n fonts/*.otf "$FD"/ 2>/dev/null || true
command -v fc-cache >/dev/null && fc-cache -f >/dev/null 2>&1 || true

# 6) 받아쓰기 모델 (처음 한 번 약 1.6GB)
if [ "${SKIP_MODEL:-0}" != "1" ]; then
  say "받아쓰기 모델(faster-whisper large-v3-turbo) 확인"
  .venv/bin/python - <<'EOF' || echo "⚠ 받아쓰기 모델을 받지 못했어요 (huggingface.co 접속이 막혀 있을 수 있어요)."
from faster_whisper import WhisperModel
WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", download_root="models")
print("받아쓰기 모델 준비 완료")
EOF
fi

mkdir -p bgm output jobs
echo
echo "✅ 설치 완료"

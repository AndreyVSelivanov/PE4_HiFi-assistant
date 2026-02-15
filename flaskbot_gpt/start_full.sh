#!/bin/bash
echo "🎧 Полный запуск Hi-Fi Assistant (Flask + Telegram)..."
source .venv/bin/activate
export USE_WEBHOOK=False
python3 main.py

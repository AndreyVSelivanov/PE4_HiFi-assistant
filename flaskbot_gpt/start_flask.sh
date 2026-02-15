#!/bin/bash
echo "🌐 Запуск только Flask-сервера..."
source .venv/bin/activate
export USE_WEBHOOK=True
python3 main.py

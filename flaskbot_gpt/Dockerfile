FROM python:3.12-slim
WORKDIR /app

# ускоряем установки
ENV PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
ENV PYTHONUNBUFFERED=1

# Flask у тебя уже слушает 0.0.0.0 и порт берёт из .env (5000). OK.
CMD ["python", "main.py"]

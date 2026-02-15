import os
import pytz
import datetime
import logging
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from telegram import Bot

from pathlib import Path
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# 1. Инициализация окружения
# ---------------------------------------------------------------------------
# грузим .env из той же директории, где лежит functions.py
load_dotenv(dotenv_path=Path(__file__).with_name('.env'))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Заявки")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Настройка логов
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)

# ---------------------------------------------------------------------------
# 2. Инициализация Telegram, OpenAI и Google Sheets
# ---------------------------------------------------------------------------
bot = Bot(token=TELEGRAM_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Авторизация в Google Sheets
credentials = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDENTIALS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets_service = build("sheets", "v4", credentials=credentials)
sheet = sheets_service.spreadsheets()

# ---------------------------------------------------------------------------
# 3. Функция добавления заявки в Google Sheets
# ---------------------------------------------------------------------------
def save_to_google_sheets(name, phone, date_str, comment):
    """
    Добавляет новую заявку в Google Sheets.
    Время фиксируется по московскому времени.
    """
    moscow_tz = pytz.timezone("Europe/Moscow")
    now = datetime.datetime.now(moscow_tz).strftime("%Y-%m-%d %H:%M:%S")

    values = [[now, name, phone, date_str, comment]]
    body = {"values": values}

    try:
        sheet.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{GOOGLE_SHEET_NAME}!A:E",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        logging.info(f"✅ Заявка сохранена: {name}, {phone}, {date_str}")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка записи в Google Sheets: {e}")
        return False

# ---------------------------------------------------------------------------
# 4. Уведомление в служебный Telegram-чат
# ---------------------------------------------------------------------------
def notify_admin(name, phone, date_str, comment):
    """
    Отправляет полное уведомление в служебный Telegram-чат.
    """
    message = (
        "📢 *Новая заявка на прослушивание!*\n\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"📅 Дата: {date_str}\n"
        f"💬 Комментарий: {comment}"
    )
    try:
        bot.send_message(
            chat_id=TELEGRAM_ADMIN_CHAT_ID,
            text=message,
            parse_mode="Markdown"
        )
        logging.info("📨 Уведомление администратору отправлено")
    except Exception as e:
        logging.error(f"Ошибка отправки уведомления: {e}")

# ---------------------------------------------------------------------------
# 5. Консультация через OpenAI Assistant API
# ---------------------------------------------------------------------------

def ask_openai(question: str, thread_id=None):
    """
    Отправляет сообщение пользователю в OpenAI Assistants API
    и возвращает JSON-ответ + thread_id.
    """
    try:
        assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
        if not assistant_id:
            raise RuntimeError("OPENAI_ASSISTANT_ID не найден в .env")

        # создаём новый thread только если нет старого
        if not thread_id:
            thread = openai_client.beta.threads.create()
            thread_id = thread.id

        openai_client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=question
        )

        run = openai_client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id
        )

        messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
        last = messages.data[0]
        answer_text = last.content[0].text.value if last.content else ""

        try:
            response = json.loads(answer_text)
        except json.JSONDecodeError:
            logging.warning("Ответ не в JSON, возвращаем как текст.")
            response = {"intent": "consult", "answer": answer_text}

        # добавляем thread_id в ответ
        response["thread_id"] = thread_id
        return response

    except Exception as e:
        logging.error(f"Ошибка OpenAI API: {e}")
        return {"intent": "error", "answer": "Ошибка при обращении к ассистенту."}


# ---------------------------------------------------------------------------
# 6. Универсальный метод обработки заявок (Telegram или веб-виджет)
# ---------------------------------------------------------------------------
def process_booking(name, phone, date_str, comment):
    """
    Единая функция: сохраняет в Google Sheets и уведомляет админа.
    """
    saved = save_to_google_sheets(name, phone, date_str, comment)
    if saved:
        notify_admin(name, phone, date_str, comment)
        return True
    return False

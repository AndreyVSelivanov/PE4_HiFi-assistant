import os
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
import asyncio

from functions import (
    process_booking,
    ask_openai,
)

# ---------------------------------------------------------------------------
# 1. Инициализация окружения и Flask
# ---------------------------------------------------------------------------
load_dotenv()

FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TILDA_URL = os.getenv("TILDA_URL")
APP_URL = os.getenv("APP_URL")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"

app = Flask(__name__)
#CORS(app, origins=[CORS_ORIGINS])
CORS(
    app,
    resources={r"/webhook/*": {"origins": [
        TILDA_URL, APP_URL
    ]}},
    supports_credentials=True
)


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)

# ---------------------------------------------------------------------------
# 2. Telegram ConversationHandler — пошаговая логика
# ---------------------------------------------------------------------------
NAME, PHONE, DATE, COMMENT = range(4)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Записаться на прослушивание", "Консультация"]]
    await update.message.reply_text(
        "Привет! 👋 Я Hi-Fi ассистент.\n"
        "Выберите режим работы:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return NAME

# выбор режима
async def handle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "прослуш" in text:
        await update.message.reply_text("Отлично! Введите ваше имя:")
        return PHONE
    else:
        await update.message.reply_text("Задайте свой вопрос о Hi-Fi системах 🎧")
        context.user_data["mode"] = "consult"
        return COMMENT

# имя
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Введите номер телефона:")
    return DATE

# телефон
async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Введите желаемую дату прослушивания:")
    return COMMENT

# дата
async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text("Добавьте комментарий (модель, пожелания):")
    return COMMENT

# комментарий

async def get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # 1. Get existing thread_id from memory
    thread_id = context.user_data.get("thread_id")

    # 2. Ask OpenAI, passing that thread_id
    response = ask_openai(user_text, thread_id=thread_id)

    # 3. Save thread_id for future turns
    context.user_data["thread_id"] = response.get("thread_id", thread_id)

    intent = response.get("intent", "consult")

    # Optional: if assistant asks for missing info
    next_q = response.get("next_question")
    if next_q:
        await update.message.reply_text(next_q)
        return

    # Normal intent handling
    if intent == "booking":
        process_booking(
            response.get("name", "—"),
            response.get("phone", "—"),
            response.get("date", "—"),
            response.get("comment", "—"),
        )
        await update.message.reply_text("✅ Заявка принята! Мы свяжемся с вами.")
    elif intent == "consult":
        await update.message.reply_text(response.get("answer", "…"))
    else:
        await update.message.reply_text("⚙️ Ошибка: не удалось обработать ответ.")


# отмена
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# ---------------------------------------------------------------------------
# 3. Flask маршруты
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "message": "HiFi Assistant Bot API working"})


@app.route("/webhook/tilda", methods=["POST"])
def tilda_webhook():
    try:
        data = request.get_json(force=True, silent=True) or {}
        app.logger.info(f"[TILDA] payload: {data}")

        user_message = data.get("message", "").strip()
        thread_id = data.get("thread_id")

        if not user_message:
            return jsonify({"error": "empty message"}), 400

        resp = ask_openai(user_message, thread_id)
        if not isinstance(resp, dict):
            app.logger.warning(f"Non-dict response from ask_openai: {resp}")
            return jsonify({"error": "invalid_response", "raw": str(resp)}), 500

        answer = (
            resp.get("answer")
            or resp.get("next_question")
            or resp.get("intent")
            or "Нет ответа от ассистента"
        )

        if answer == "booking":
            process_booking(
                resp.get("name", "—"),
                resp.get("phone", "—"),
                resp.get("date", "—"),
                resp.get("comment", "—"),
            )
            answer = "✅ Заявка принята! Мы свяжемся с вами."
        
        result = {"answer": answer, "thread_id": resp.get("thread_id")}
        app.logger.info(f"[TILDA] result: {result}")

        return jsonify(result)

    except Exception as e:
        app.logger.exception("Webhook /tilda failed")
        return jsonify({"error": "server_error", "details": str(e)}), 500


# ---------------------------------------------------------------------------
# 4. Запуск Telegram-бота
# ---------------------------------------------------------------------------

def run_telegram_bot():
    """
    Упрощённый Telegram-бот: отправляет сообщения в OpenAI Assistant
    и выполняет действия в зависимости от intent (booking / consult).
    """
    from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
    import asyncio
    from functions import ask_openai, process_booking

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Здравствуйте! Я Hi-Fi ассистент 🎧\n"
            "Задайте вопрос или напишите, что хотите записаться на прослушивание."
        )

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_text = update.message.text

        # получить thread_id из памяти
        thread_id = context.user_data.get("thread_id")

        # передать его ассистенту
        response = ask_openai(user_text, thread_id=thread_id)

        # сохранить thread_id для следующих сообщений
        if not context.user_data.get("thread_id") and "thread_id" in response:
            context.user_data["thread_id"] = response["thread_id"]

        intent = response.get("intent", "consult")

        # если ассистент хочет уточнить — продолжаем диалог
        next_q = response.get("next_question")
        if next_q:
            await update.message.reply_text(next_q)
            return

        if intent == "booking":
            name = response.get("name", "Не указано")
            phone = response.get("phone", "Не указано")
            date_str = response.get("date", "Не указано")
            comment = response.get("comment", "—")
            process_booking(name, phone, date_str, comment)
            await update.message.reply_text("✅ Заявка принята! Мы свяжемся с вами.")
        elif intent == "consult":
            await update.message.reply_text(response.get("answer", "…"))
        else:
            await update.message.reply_text("⚙️ Ошибка: не удалось определить ответ.")


    # создаём приложение
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # добавляем хендлеры
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("🤖 Telegram-бот запущен (Assistant-режим)…")
    application.run_polling()


# ---------------------------------------------------------------------------
# 5. Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if USE_WEBHOOK:
        logging.info("Запуск Flask в режиме webhook для Telegram")
        app.run(host="0.0.0.0", port=FLASK_PORT)
    else:
        # 1) Стартуем Flask в отдельном daemon-потоке
        from threading import Thread

        def run_flask():
            logging.info(f"🌐 Flask сервер запущен на порту {FLASK_PORT}")
            # В проде замените встроенный сервер на gunicorn/uvicorn
            app.run(host="0.0.0.0", port=FLASK_PORT)

        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()

        # 2) В главном потоке запускаем Telegram long polling (блокирующе)
        run_telegram_bot()

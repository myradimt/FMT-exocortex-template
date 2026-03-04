import os
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, CommandHandler, filters, ContextTypes
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

def get_claude():
    return anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

# Главное меню
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 План на сегодня", callback_data="plan")],
        [InlineKeyboardButton("✏️ Заметка", callback_data="note"),
         InlineKeyboardButton("📌 Задача (РП)", callback_data="task")],
        [InlineKeyboardButton("🔓 Открытие сессии", callback_data="open"),
         InlineKeyboardButton("🔒 Закрытие сессии", callback_data="close")],
        [InlineKeyboardButton("❓ Вопрос к базе знаний", callback_data="question")],
        [InlineKeyboardButton("📊 Урок / инсайт", callback_data="lesson")],
    ]
    return InlineKeyboardMarkup(keyboard)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой IWE-ассистент.\nВыбери действие:",
        reply_markup=main_menu()
    )

# Обработка кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    prompts = {
        "plan": "Составь краткий план на сегодня в стиле IWE. Напомни про WP Gate и протокол ОРЗ.",
        "open": "Помоги открыть рабочую сессию по протоколу ОРЗ. Спроси какая задача и проверь WP Gate.",
        "close": "Помоги закрыть рабочую сессию по протоколу ОРЗ. Напомни про Capture, коммит и обновление MEMORY.md.",
        "note": "Пользователь хочет сделать заметку. Попроси текст заметки и подтверди что сохранишь её.",
        "task": "Помоги сформулировать новый РП (рабочий продукт) по правилам IWE — существительное, измеримый артефакт.",
        "question": "Пользователь задаст вопрос по базе знаний IWE. Попроси его написать вопрос.",
        "lesson": "Пользователь хочет записать урок или инсайт. Попроси описать что узнал и сформулируй в виде правила для MEMORY.md.",
    }

    prompt = prompts.get(data, "Помоги пользователю.")

    response = get_claude().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system="Ты IWE-ассистент. Отвечай кратко, по делу, на русском. Знаешь протоколы ОРЗ, WP Gate, Capture-to-Pack, MEMORY.md.",
        messages=[{"role": "user", "content": prompt}]
    )

    reply = response.content[0].text
    await query.message.reply_text(reply, reply_markup=main_menu())

# Обычные сообщения
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    response = get_claude().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system="Ты IWE-ассистент. Отвечай кратко, по делу, на русском. Знаешь протоколы ОРЗ, WP Gate, Capture-to-Pack, MEMORY.md.",
        messages=[{"role": "user", "content": user_text}]
    )

    reply = response.content[0].text
    await update.message.reply_text(reply, reply_markup=main_menu())

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("IWE-бот запущен!")
app.run_polling()
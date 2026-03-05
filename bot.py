import os
import requests
import base64
from datetime import datetime
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, CommandHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))
GITHUB_REPO = "myradimt/FMT-exocortex-template"

# История диалогов
conversation_history = defaultdict(list)
MAX_HISTORY = 20

# Состояния пошаговых флоу
user_states = {}
# user_states[user_id] = {
#   "flow": "task" | "lesson",
#   "step": 0,
#   "answers": []
# }

# ─── Claude ───────────────────────────────────────────────────────────────────

def get_claude():
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ─── GitHub ───────────────────────────────────────────────────────────────────

def github_get(path: str):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers, timeout=5)
    if r.status_code == 200:
        return r.json()
    return None

def github_put(path: str, content: str, message: str):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    existing = github_get(path)
    data = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if existing:
        data["sha"] = existing["sha"]
    requests.put(url, headers=headers, json=data, timeout=5)

def load_file_from_github(path: str) -> str:
    data = github_get(path)
    if data and "content" in data:
        return base64.b64decode(data["content"]).decode()
    return ""

def load_memory() -> str:
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/memory/MEMORY.md"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

def save_note(text: str):
    path = "memory/notes.md"
    existing = load_file_from_github(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = existing + f"\n## {now}\n{text}\n"
    github_put(path, updated, f"note: {now}")

def save_session_log(action: str, details: str):
    path = "memory/sessions.md"
    existing = load_file_from_github(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = existing + f"\n## {action} — {now}\n{details}\n"
    github_put(path, updated, f"session: {action} {now}")

def save_lesson(lesson_text: str):
    path = "memory/lessons.md"
    existing = load_file_from_github(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = existing + f"\n## Урок — {now}\n{lesson_text}\n"
    github_put(path, updated, f"lesson: {now}")

def save_task(task_text: str):
    path = "memory/tasks.md"
    existing = load_file_from_github(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = existing + f"\n## РП — {now}\n{task_text}\n[ ] in_progress\n"
    github_put(path, updated, f"task: {now}")

def mark_task_done(task_name: str):
    path = "memory/tasks.md"
    existing = load_file_from_github(path)
    updated = existing.replace(f"[ ] in_progress", f"[x] done", 1)
    github_put(path, updated, f"task done: {task_name}")

# ─── Системный промпт ─────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    memory = load_memory()
    base = "Ты IWE-ассистент. Отвечай кратко, по делу, на русском. Знаешь протоколы ОРЗ, WP Gate, Capture-to-Pack, MEMORY.md."
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if memory:
        return f"{base}\n\nТекущая дата и время: {now}\n\n=== MEMORY.md ===\n{memory}"
    return f"{base}\n\nТекущая дата и время: {now}"

# ─── История ──────────────────────────────────────────────────────────────────

def add_to_history(user_id: int, role: str, content: str):
    conversation_history[user_id].append({"role": role, "content": content})
    if len(conversation_history[user_id]) > MAX_HISTORY * 2:
        conversation_history[user_id] = conversation_history[user_id][-MAX_HISTORY * 2:]

def get_history(user_id: int) -> list:
    return conversation_history[user_id]

# ─── Защита ───────────────────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    if ALLOWED_USER_ID == 0:
        return True
    return user_id == ALLOWED_USER_ID

# ─── Меню ─────────────────────────────────────────────────────────────────────

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 План на сегодня", callback_data="plan")],
        [InlineKeyboardButton("✏️ Заметка", callback_data="note"),
         InlineKeyboardButton("📌 Задача (РП)", callback_data="task")],
        [InlineKeyboardButton("🔓 Открытие сессии", callback_data="open"),
         InlineKeyboardButton("🔒 Закрытие сессии", callback_data="close")],
        [InlineKeyboardButton("❓ Вопрос к базе знаний", callback_data="question")],
        [InlineKeyboardButton("📊 Урок / инсайт", callback_data="lesson")],
        [InlineKeyboardButton("📰 Дайджест недели", callback_data="digest"),
         InlineKeyboardButton("🗑 Очистить историю", callback_data="clear")],
    ]
    return InlineKeyboardMarkup(keyboard)

def plan_menu():
    keyboard = [
        [InlineKeyboardButton("✅ Сделано", callback_data="plan_done"),
         InlineKeyboardButton("⚙️ Работаю", callback_data="plan_wip")],
        [InlineKeyboardButton("📋 Меню", callback_data="show_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ─── Пошаговые флоу ───────────────────────────────────────────────────────────

TASK_QUESTIONS = [
    "1️⃣ *Что ты хочешь создать/получить?*\n(существительное: документ, конфиг, чек-лист, протокол и т.д.)",
    "2️⃣ *Как его измерить?*\n(критерий готовности: «содержит X разделов», «протестировано на Y», «согласовано с Z»)",
    "3️⃣ *К когда?*\n(дедлайн в рамках текущей недели или позже?)",
    "4️⃣ *Зачем?*\n(какую проблему решает, на какой процесс влияет?)",
]

LESSON_QUESTIONS = [
    "1️⃣ *Что ты узнал/открыл?*\n(конкретный факт, принцип, ошибка, паттерн)",
    "2️⃣ *В каком контексте это применяется?*\n(когда, где, при каких условиях это актуально)",
    "3️⃣ *Какое правило/различие отсюда следует?*\n(формулировка: «ЕСЛИ X, ТО Y» или «X ≠ Y потому что...»)",
]

async def ask_next_step(update_or_message, user_id: int):
    state = user_states[user_id]
    flow = state["flow"]
    step = state["step"]

    if flow == "task":
        questions = TASK_QUESTIONS
    else:
        questions = LESSON_QUESTIONS

    if step < len(questions):
        await update_or_message.reply_text(questions[step], parse_mode="Markdown")
    else:
        # Все ответы собраны
        answers = state["answers"]
        if flow == "task":
            summary = (
                f"**Новый РП сформулирован:**\n\n"
                f"📦 Артефакт: {answers[0]}\n"
                f"📏 Критерий: {answers[1]}\n"
                f"📅 Дедлайн: {answers[2]}\n"
                f"🎯 Цель: {answers[3]}"
            )
            save_task("\n".join([
                f"Артефакт: {answers[0]}",
                f"Критерий: {answers[1]}",
                f"Дедлайн: {answers[2]}",
                f"Цель: {answers[3]}",
            ]))
        else:
            prompt = (
                f"Сформулируй урок/инсайт в виде правила для MEMORY.md на основе ответов:\n"
                f"1. Что узнал: {answers[0]}\n"
                f"2. Контекст: {answers[1]}\n"
                f"3. Правило: {answers[2]}"
            )
            response = get_claude().messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=build_system_prompt(),
                messages=[{"role": "user", "content": prompt}]
            )
            summary = response.content[0].text
            save_lesson("\n".join([
                f"Что узнал: {answers[0]}",
                f"Контекст: {answers[1]}",
                f"Правило: {answers[2]}",
                f"Формулировка: {summary}",
            ]))

        del user_states[user_id]
        await update_or_message.reply_text(summary, parse_mode="Markdown")

# ─── Handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    conversation_history[user_id].clear()
    user_states.pop(user_id, None)
    await update.message.reply_text(
        "👋 Привет! Я твой IWE-ассистент.\nВыбери действие:",
        reply_markup=main_menu()
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    await update.message.reply_text("Выбери действие:", reply_markup=main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not is_allowed(user_id):
        await query.message.reply_text("⛔ Доступ запрещён.")
        return

    data = query.data

    if data == "show_menu":
        await query.message.reply_text("Выбери действие:", reply_markup=main_menu())
        return

    if data == "clear":
        conversation_history[user_id].clear()
        user_states.pop(user_id, None)
        await query.message.reply_text("🗑 История очищена!")
        return

    if data == "plan_done":
        mark_task_done("current")
        await query.message.reply_text("✅ Статус обновлён — задача выполнена!")
        return

    if data == "plan_wip":
        await query.message.reply_text("⚙️ Отлично, работаем! Удачи 💪")
        return

    if data == "digest":
        notes = load_file_from_github("memory/notes.md")
        if not notes:
            await query.message.reply_text("📭 Заметок пока нет.")
            return
        prompt = f"Сделай краткий дайджест заметок за неделю. Выдели главные инсайты и незакрытые задачи:\n\n{notes[-3000:]}"
        response = get_claude().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=build_system_prompt(),
            messages=[{"role": "user", "content": prompt}]
        )
        await query.message.reply_text(f"📰 Дайджест:\n\n{response.content[0].text}")
        return

    # Пошаговые флоу
    if data == "task":
        user_states[user_id] = {"flow": "task", "step": 0, "answers": []}
        await ask_next_step(query.message, user_id)
        return

    if data == "lesson":
        user_states[user_id] = {"flow": "lesson", "step": 0, "answers": []}
        await ask_next_step(query.message, user_id)
        return

    # Обычные промпты
    prompts = {
        "plan": (
            "Составь очень краткий план на сегодня: только активный РП и топ-3 задачи. "
            "Без таблиц и заголовков — просто список. Используй MEMORY.md."
        ),
        "open": "Помоги открыть рабочую сессию по протоколу ОРЗ. Посмотри в MEMORY.md — что сейчас в работе? Спроси какая задача и проверь WP Gate.",
        "close": "Помоги закрыть рабочую сессию по протоколу ОРЗ. Напомни про Capture, коммит и обновление MEMORY.md.",
        "note": "Пользователь хочет сделать заметку. Попроси текст заметки.",
        "question": "Пользователь задаст вопрос по базе знаний IWE. Используй MEMORY.md для ответа. Попроси написать вопрос.",
    }

    prompt = prompts.get(data, "Помоги пользователю.")
    add_to_history(user_id, "user", prompt)

    response = get_claude().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=build_system_prompt(),
        messages=get_history(user_id)
    )

    reply = response.content[0].text

    if data == "open":
        save_session_log("🔓 Открытие", reply[:500])
    elif data == "close":
        save_session_log("🔒 Закрытие", reply[:500])

    add_to_history(user_id, "assistant", reply)

    if data == "plan":
        await query.message.reply_text(reply, reply_markup=plan_menu())
    else:
        await query.message.reply_text(reply)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    user_text = update.message.text

    # Пошаговый флоу
    if user_id in user_states:
        state = user_states[user_id]
        state["answers"].append(user_text)
        state["step"] += 1
        await ask_next_step(update.message, user_id)
        return

    add_to_history(user_id, "user", user_text)

    response = get_claude().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=build_system_prompt(),
        messages=get_history(user_id)
    )

    reply = response.content[0].text

    if "SAVE_NOTE:" in reply:
        note_text = reply.split("SAVE_NOTE:")[-1].strip()
        save_note(note_text)
        reply = reply.replace(f"SAVE_NOTE:{note_text}", "").strip()
        reply += "\n\n✅ Заметка сохранена в GitHub!"

    add_to_history(user_id, "assistant", reply)
    await update.message.reply_text(reply)

# ─── Еженедельный дайджест ────────────────────────────────────────────────────

async def send_weekly_digest(app):
    if ALLOWED_USER_ID == 0:
        return
    notes = load_file_from_github("memory/notes.md")
    if not notes:
        return
    prompt = f"Сделай краткий дайджест заметок за неделю. Выдели главные инсайты и незакрытые задачи:\n\n{notes[-3000:]}"
    response = get_claude().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=build_system_prompt(),
        messages=[{"role": "user", "content": prompt}]
    )
    await app.bot.send_message(chat_id=ALLOWED_USER_ID, text=f"📰 Дайджест недели:\n\n{response.content[0].text}")

# ─── Запуск ───────────────────────────────────────────────────────────────────

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("menu", menu_command))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

scheduler = AsyncIOScheduler()
scheduler.add_job(send_weekly_digest, "cron", day_of_week="sun", hour=9, minute=0, args=[app])
scheduler.start()

print("IWE-бот запущен!")
app.run_polling()

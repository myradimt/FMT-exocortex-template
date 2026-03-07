import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    CommandHandler, filters, ContextTypes
)
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")

claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# ─── Системный промпт агента ────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты IWE-ассистент (Intellectual Working Environment).
Отвечай кратко, по делу, на русском языке.

Ты знаешь и применяешь:
- Протокол ОРЗ: Открытие → Работа → Закрытие
- WP Gate: проверка задачи по плану перед началом работы
- Capture-to-Pack: фиксация знаний на рубежах («Capture: [что] → [куда]»)
- MEMORY.md: оперативная память (задачи, статусы, уроки)
- CLAUDE.md: правила и протоколы агента
- Pack: структурированные знания домена
- 7 типов заметок: НЭП, Задача, Знание, Черновик, Идея, Личное, Шум
- ArchGate ЭМОГССБ: оценка архитектурных решений (средняя ≥8)
- РП (Рабочий Продукт): измеримый артефакт, формулируется существительным

Метафора системы: не протез, а экзоскелет — усиливает, не заменяет.
Ничего не записывается в Pack без подтверждения пользователя."""

# ─── Главное меню ───────────────────────────────────────────────────────────
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 План на сегодня", callback_data="plan")],
        [
            InlineKeyboardButton("✏️ Заметка", callback_data="note"),
            InlineKeyboardButton("📌 Новый РП", callback_data="task"),
        ],
        [
            InlineKeyboardButton("🔓 Открытие сессии", callback_data="open"),
            InlineKeyboardButton("🔒 Закрытие сессии", callback_data="close"),
        ],
        [InlineKeyboardButton("🗂 Разобрать заметки", callback_data="note_review")],
        [
            InlineKeyboardButton("❓ Вопрос к базе знаний", callback_data="question"),
            InlineKeyboardButton("💡 Урок / инсайт", callback_data="lesson"),
        ],
        [InlineKeyboardButton("📊 Недельный обзор", callback_data="week_review")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ─── /start ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой IWE-ассистент.\n\n"
        "Быстрые команды:\n"
        "• `.заметка текст` — сохранить мысль\n"
        "• `?вопрос` — спросить базу знаний\n"
        "• Перешли сообщение + комментарий — сохранится как заметка\n\n"
        "Выбери действие:",
        reply_markup=main_menu()
    )

# ─── /help ──────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Справка IWE-бота*\n\n"
        "*Быстрый ввод:*\n"
        "`. текст` — заметка (точка + пробел)\n"
        "`? текст` — вопрос к базе знаний\n"
        "`/plan` — план на сегодня\n"
        "`/open` — открыть сессию\n"
        "`/close` — закрыть сессию\n"
        "`/review` — разобрать заметки\n"
        "`/week` — недельный обзор\n\n"
        "*Пересылка сообщений:*\n"
        "Перешли любое сообщение из другого чата "
        "и добавь свой комментарий — оба текста сохранятся как заметка.\n\n"
        "*7 типов заметок:*\n"
        "НЭП · Задача · Знание · Черновик · Идея · Личное · Шум"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

# ─── Классификация заметки ───────────────────────────────────────────────────
async def classify_note(note_text: str) -> str:
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Классифицируй эту заметку по одному из 7 типов IWE:\n"
                f"НЭП (неудовлетворённость/проблема), Задача (→ план), "
                f"Знание (→ Pack), Черновик (→ пост), Идея (🔄), Личное, Шум.\n\n"
                f"Заметка: «{note_text}»\n\n"
                f"Ответь строго в формате:\n"
                f"Тип: [тип]\nКуда: [куда сохранить]\nДействие: [что сделать одной строкой]"
            )
        }]
    )
    return response.content[0].text

# ─── Обработка кнопок ───────────────────────────────────────────────────────
BUTTON_PROMPTS = {
    "plan": (
        "Составь краткий план дня в стиле IWE. "
        "Напомни про WP Gate и протокол ОРЗ. "
        "Укажи 3-5 РП на сегодня в формате списка."
    ),
    "open": (
        "Помоги открыть рабочую сессию по протоколу ОРЗ. "
        "Спроси какая задача, проверь WP Gate, "
        "объяви ритуал согласования: Роль / Работа / РП / Метод / Оценка."
    ),
    "close": (
        "Помоги закрыть рабочую сессию по протоколу ОРЗ. "
        "Напомни про: Capture (что зафиксировано), "
        "обновление MEMORY.md, git commit + push, отчёт Close."
    ),
    "note": (
        "Пользователь хочет сделать заметку. "
        "Напомни что можно написать `. текст` для быстрого сохранения. "
        "Объясни 7 типов заметок IWE кратко."
    ),
    "task": (
        "Помоги сформулировать новый РП (рабочий продукт) по правилам IWE: "
        "существительное, измеримый артефакт, можно распечатать. "
        "Не 'изучить', не 'разобраться' — а 'документ', 'схема', 'план'. "
        "Спроси у пользователя что он хочет сделать и помоги сформулировать РП."
    ),
    "note_review": (
        "Выступи в роли Стратега (Note-Review). "
        "Объясни как работает автоматическая классификация заметок в IWE: "
        "7 типов → НЭП, Задача, Знание, Черновик, Идея, Личное, Шум. "
        "Спроси какие заметки нужно разобрать или предложи запустить Note-Review вручную."
    ),
    "question": (
        "Пользователь хочет задать вопрос по базе знаний IWE. "
        "Напомни что можно написать `? текст вопроса` для быстрого доступа. "
        "Попроси написать вопрос."
    ),
    "lesson": (
        "Пользователь хочет записать урок или инсайт. "
        "Попроси описать что узнал и сформулируй в виде правила для MEMORY.md. "
        "Формат: 'Урок: [суть одной строкой]'"
    ),
    "week_review": (
        "Проведи недельный обзор в стиле IWE. "
        "Задай три вопроса: "
        "1) Какие РП выполнены на этой неделе? "
        "2) Что не получилось и почему? "
        "3) Что изменить в следующей неделе? "
        "После ответов — помоги обновить MEMORY.md."
    ),
}

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    prompt = BUTTON_PROMPTS.get(data, "Помоги пользователю в рамках IWE.")
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    await query.message.reply_text(response.content[0].text, reply_markup=main_menu())

# ─── Обработка текстовых сообщений ──────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text or ""

    # 1. Быстрая заметка: ". текст" или ".текст"
    if text.startswith("."):
        note_text = text[1:].strip()
        if not note_text:
            await msg.reply_text("Напиши заметку после точки: `.текст заметки`")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        classification = await classify_note(note_text)
        await msg.reply_text(
            f"✅ *Заметка сохранена* [{timestamp}]\n\n"
            f"📝 `{note_text}`\n\n"
            f"🗂 *Классификация:*\n{classification}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    # 2. Вопрос к базе знаний: "? вопрос"
    if text.startswith("?"):
        question = text[1:].strip()
        if not question:
            await msg.reply_text("Напиши вопрос после знака вопроса: `?что такое ОРЗ`")
            return
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Вопрос по базе знаний IWE: {question}"}]
        )
        await msg.reply_text(
            f"❓ *Вопрос:* {question}\n\n{response.content[0].text}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    # 3. Пересланное сообщение + комментарий
    if msg.forward_date or msg.forward_from or msg.forward_from_chat:
        forwarded_text = text or "[медиа без текста]"
        comment = context.user_data.get("pending_comment", "")
        note_combined = f"[Переслано] {forwarded_text}"
        if comment:
            note_combined += f"\n[Комментарий] {comment}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        classification = await classify_note(note_combined)
        await msg.reply_text(
            f"✅ *Переслано и сохранено* [{timestamp}]\n\n"
            f"🗂 *Классификация:*\n{classification}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        context.user_data["pending_forward"] = forwarded_text
        return

    # 4. Комментарий к пересланному
    if context.user_data.get("pending_forward"):
        forwarded = context.user_data.pop("pending_forward")
        note_combined = f"[Переслано] {forwarded}\n[Комментарий] {text}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        classification = await classify_note(note_combined)
        await msg.reply_text(
            f"✅ *Заметка с комментарием сохранена* [{timestamp}]\n\n"
            f"🗂 *Классификация:*\n{classification}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    # 5. Обычный вопрос / диалог
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}]
    )
    await msg.reply_text(response.content[0].text, reply_markup=main_menu())

# ─── Команды ────────────────────────────────────────────────────────────────
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pending_button"] = "plan"
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": BUTTON_PROMPTS["plan"]}]
    )
    await update.message.reply_text(response.content[0].text, reply_markup=main_menu())

async def cmd_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": BUTTON_PROMPTS["open"]}]
    )
    await update.message.reply_text(response.content[0].text, reply_markup=main_menu())

async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": BUTTON_PROMPTS["close"]}]
    )
    await update.message.reply_text(response.content[0].text, reply_markup=main_menu())

async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": BUTTON_PROMPTS["note_review"]}]
    )
    await update.message.reply_text(response.content[0].text, reply_markup=main_menu())

async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": BUTTON_PROMPTS["week_review"]}]
    )
    await update.message.reply_text(response.content[0].text, reply_markup=main_menu())

# ─── Запуск ─────────────────────────────────────────────────────────────────
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("plan", cmd_plan))
app.add_handler(CommandHandler("open", cmd_open))
app.add_handler(CommandHandler("close", cmd_close))
app.add_handler(CommandHandler("review", cmd_review))
app.add_handler(CommandHandler("week", cmd_week))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 IWE-бот запущен!")
app.run_polling()

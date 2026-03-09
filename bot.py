import os
import glob
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    CommandHandler, filters, ContextTypes
)
import anthropic

# ─── Конфигурация ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")

# Путь к экзокортексу — ПОМЕНЯЙТЕ на свой
WORKSPACE = os.environ.get("IWE_WORKSPACE", os.path.expanduser("~/Github"))
EXOCORTEX = os.path.join(WORKSPACE, "FMT-exocortex-template")
DS_STRATEGY = os.path.join(WORKSPACE, "DS-strategy")
MEMORY_FILE = os.path.join(EXOCORTEX, "memory", "MEMORY.md")

claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# ─── Утилиты для работы с файлами ───────────────────────────────────────────

def ensure_dirs():
    """Создать все нужные папки если их нет."""
    for d in [
        os.path.join(DS_STRATEGY, "inbox"),
        os.path.join(DS_STRATEGY, "current"),
        os.path.join(DS_STRATEGY, "archive"),
        os.path.join(DS_STRATEGY, "docs"),
    ]:
        os.makedirs(d, exist_ok=True)

def read_file(path: str) -> str:
    """Прочитать файл, вернуть '' если не существует."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

def write_file(path: str, content: str):
    """Записать файл, создав папки если нужно."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def append_file(path: str, content: str):
    """Дописать в файл."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)

def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def week_number() -> str:
    return f"W{datetime.now().isocalendar()[1]:02d}"

def find_latest_file(directory: str, prefix: str) -> str:
    """Найти самый свежий файл по префиксу."""
    pattern = os.path.join(directory, f"{prefix}*.md")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else ""

# ─── Чтение состояния экзокортекса ──────────────────────────────────────────

def get_memory() -> str:
    return read_file(MEMORY_FILE)

def get_today_plan() -> str:
    path = os.path.join(DS_STRATEGY, "current", f"DayPlan-{today()}.md")
    content = read_file(path)
    if not content:
        latest = find_latest_file(os.path.join(DS_STRATEGY, "current"), "DayPlan-")
        if latest:
            content = f"[Нет плана на сегодня. Последний план:]\n\n{read_file(latest)}"
        else:
            content = "[Нет ни одного DayPlan. Создайте через /open]"
    return content

def get_week_plan() -> str:
    wn = week_number()
    path = os.path.join(DS_STRATEGY, "current", f"WeekPlan-{wn}.md")
    content = read_file(path)
    if not content:
        latest = find_latest_file(os.path.join(DS_STRATEGY, "current"), "WeekPlan-")
        if latest:
            content = read_file(latest)
        else:
            content = "[Нет WeekPlan. Создайте через /week]"
    return content

def get_strategy() -> str:
    return read_file(os.path.join(DS_STRATEGY, "docs", "Strategy.md"))

def get_dissatisfactions() -> str:
    return read_file(os.path.join(DS_STRATEGY, "docs", "Dissatisfactions.md"))

def get_notes() -> str:
    return read_file(os.path.join(DS_STRATEGY, "inbox", "notes.md"))

def get_today_captures() -> str:
    path = os.path.join(DS_STRATEGY, "inbox", f"capture-{today()}.md")
    return read_file(path)

# ─── Запись в экзокортекс ────────────────────────────────────────────────────

def save_note(text: str):
    """Сохранить быструю заметку в notes.md."""
    path = os.path.join(DS_STRATEGY, "inbox", "notes.md")
    entry = f"\n- [{now_str()}] {text}\n"
    if not os.path.exists(path):
        write_file(path, f"# notes.md — Быстрые заметки\n\n## Заметки\n{entry}")
    else:
        append_file(path, entry)

def save_capture(note_text: str, classification: str):
    """Сохранить классифицированный capture."""
    path = os.path.join(DS_STRATEGY, "inbox", f"capture-{today()}.md")
    entry = f"\n### [{now_str()}] {note_text[:60]}...\n"
    entry += f"- **Текст:** {note_text}\n"
    entry += f"- **Классификация:**\n{classification}\n"
    entry += f"---\n"

    if not os.path.exists(path):
        header = (
            f"# capture-{today()} — Captures сессии\n\n"
            f"- **Дата:** {today()}\n"
            f"- **Статус:** new\n\n"
            f"## Captures\n"
        )
        write_file(path, header + entry)
    else:
        append_file(path, entry)

def save_day_plan(plan_text: str):
    """Сохранить план дня."""
    path = os.path.join(DS_STRATEGY, "current", f"DayPlan-{today()}.md")
    write_file(path, plan_text)

def save_week_plan(plan_text: str):
    """Сохранить план недели."""
    wn = week_number()
    path = os.path.join(DS_STRATEGY, "current", f"WeekPlan-{wn}.md")
    write_file(path, plan_text)

def save_week_review(review_text: str):
    """Сохранить недельный обзор в архив."""
    wn = week_number()
    path = os.path.join(DS_STRATEGY, "archive", f"WeekReview-{wn}.md")
    write_file(path, review_text)

def update_memory(new_content: str):
    """Обновить MEMORY.md."""
    write_file(MEMORY_FILE, new_content)

# ─── Системный промпт с реальным контекстом ─────────────────────────────────

def build_system_prompt(include_memory=True, include_plan=False) -> str:
    base = """Ты IWE-ассистент (Intellectual Working Environment) в Telegram.
Отвечай кратко, по делу, на русском. Используй форматирование Markdown.

Ты РЕАЛЬНО работаешь с файлами экзокортекса:
- Заметки сохраняются в DS-strategy/inbox/notes.md
- Captures классифицируются и записываются в DS-strategy/inbox/capture-ДАТА.md
- Планы дня — DS-strategy/current/DayPlan-ДАТА.md
- Планы недели — DS-strategy/current/WeekPlan-WНН.md
- Оперативная память — memory/MEMORY.md

Протоколы:
- /open: загрузить контекст, показать план, определить задачу
- /close: зафиксировать результат, обновить MEMORY.md
- /review: сравнить план с фактом
- /week: недельное планирование

7 типов заметок: НЭП, Задача, Знание, Черновик, Идея, Личное, Шум

Когда пишешь план дня или недели, используй ТОЧНЫЙ формат markdown
который можно сохранить как файл."""

    if include_memory:
        memory = get_memory()
        if memory:
            base += f"\n\n--- ТЕКУЩАЯ ПАМЯТЬ (MEMORY.md) ---\n{memory[:2000]}\n--- КОНЕЦ ПАМЯТИ ---"

    if include_plan:
        plan = get_today_plan()
        if plan and "[Нет" not in plan:
            base += f"\n\n--- ПЛАН ДНЯ ---\n{plan[:1500]}\n--- КОНЕЦ ПЛАНА ---"

        wplan = get_week_plan()
        if wplan and "[Нет" not in wplan:
            base += f"\n\n--- ПЛАН НЕДЕЛИ ---\n{wplan[:1500]}\n--- КОНЕЦ ПЛАНА НЕДЕЛИ ---"

    return base

# ─── Классификация заметки ───────────────────────────────────────────────────

async def classify_note(note_text: str) -> str:
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="Классифицируй заметку. Ответь СТРОГО в 3 строки.",
        messages=[{
            "role": "user",
            "content": (
                f"Классифицируй заметку по 7 типам IWE:\n"
                f"НЭП, Задача, Знание, Черновик, Идея, Личное, Шум.\n\n"
                f"Заметка: «{note_text}»\n\n"
                f"Ответ строго:\n"
                f"Тип: [тип]\nКуда: [файл/раздел]\nДействие: [одна строка]"
            )
        }]
    )
    return response.content[0].text

# ─── Меню ────────────────────────────────────────────────────────────────────

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 План на сегодня", callback_data="plan")],
        [
            InlineKeyboardButton("✏️ Заметка", callback_data="note"),
            InlineKeyboardButton("📌 Новый РП", callback_data="task"),
        ],
        [
            InlineKeyboardButton("🔓 /open", callback_data="open"),
            InlineKeyboardButton("🔒 /close", callback_data="close"),
        ],
        [InlineKeyboardButton("🗂 Разобрать заметки", callback_data="note_review")],
        [
            InlineKeyboardButton("❓ Вопрос", callback_data="question"),
            InlineKeyboardButton("💡 Урок", callback_data="lesson"),
        ],
        [InlineKeyboardButton("📊 Неделя /week", callback_data="week_review")],
    ]
    return InlineKeyboardMarkup(keyboard)

def collapse_menu():
    """Свёрнутое меню — одна кнопка."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☰ Меню", callback_data="show_menu")]
    ])

# ─── /start ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_dirs()
    memory = get_memory()
    status = ""
    if memory:
        # Извлечь первые строки с РП
        lines = [l for l in memory.split("\n") if "|" in l and "РП" not in l and "---" not in l and "#" not in l]
        if lines:
            status = "\n".join(lines[:5])

    text = (
        f"👋 *IWE-ассистент запущен*\n"
        f"📅 {today()} | 📆 {week_number()}\n\n"
    )
    if status:
        text += f"📊 *Активные РП:*\n```\n{status}\n```\n\n"

    text += (
        "⚡ *Быстрые команды:*\n"
        "`. текст` — сохранить заметку\n"
        "`? вопрос` — спросить базу\n"
        "`/open` `/close` `/review` `/week` `/help`"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

# ─── /help ───────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Справка IWE*\n\n"
        "*Команды:*\n"
        "`/open` — открыть сессию (загрузить контекст)\n"
        "`/close` — закрыть сессию (сохранить результат)\n"
        "`/plan` — план на сегодня\n"
        "`/review` — разобрать заметки из inbox\n"
        "`/week` — недельное планирование\n\n"
        "*Быстрый ввод:*\n"
        "`. текст` — заметка → `notes.md`\n"
        "`? вопрос` — вопрос к базе знаний\n\n"
        "*Куда пишутся данные:*\n"
        "📝 Заметки → `DS-strategy/inbox/notes.md`\n"
        "🗂 Captures → `DS-strategy/inbox/capture-ДАТА.md`\n"
        "📋 Планы дня → `DS-strategy/current/DayPlan-ДАТА.md`\n"
        "📊 Планы недели → `DS-strategy/current/WeekPlan-WНН.md`\n"
        "🧠 Память → `memory/MEMORY.md`\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=collapse_menu())

# ─── /open — Открытие сессии ─────────────────────────────────────────────────

async def cmd_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_dirs()
    memory = get_memory()
    day_plan = get_today_plan()
    week_plan = get_week_plan()

    # Собрать контекст для Claude
    context_text = f"MEMORY.md:\n{memory[:1500]}\n\nDayPlan:\n{day_plan[:1000]}\n\nWeekPlan:\n{week_plan[:1000]}"

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=build_system_prompt(include_memory=True, include_plan=True),
        messages=[{
            "role": "user",
            "content": (
                f"Открываю сессию. Сейчас {now_str()}, {week_number()}.\n\n"
                f"Покажи:\n"
                f"1. 📅 Дата и неделя\n"
                f"2. 🎯 Активные РП из MEMORY.md (таблица)\n"
                f"3. ⚡ Фокус дня из DayPlan (если есть)\n"
                f"4. 🚫 Блокеры (если есть)\n\n"
                f"Затем спроси: «Над чем работаем?»\n"
                f"Формат — краткий, телеграм-дружелюбный."
            )
        }]
    )

    # Записать в notes что сессия открыта
    save_note(f"🔓 Сессия открыта")

    await update.message.reply_text(
        response.content[0].text,
        parse_mode="Markdown",
        reply_markup=collapse_menu()
    )

# ─── /close — Закрытие сессии ────────────────────────────────────────────────

async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = get_memory()
    notes = get_notes()
    captures = get_today_captures()

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system=build_system_prompt(include_memory=True, include_plan=True),
        messages=[{
            "role": "user",
            "content": (
                f"Закрываю сессию. Сейчас {now_str()}.\n\n"
                f"Заметки за сегодня (notes.md):\n{notes[-1000:] if notes else '[пусто]'}\n\n"
                f"Captures за сегодня:\n{captures[-1000:] if captures else '[пусто]'}\n\n"
                f"Сделай:\n"
                f"1. ✅ Итог: что сделано сегодня (из заметок и captures)\n"
                f"2. 🔄 Что в процессе\n"
                f"3. ➡️ Следующий шаг на завтра\n"
                f"4. 💡 Инсайты/уроки (если были)\n\n"
                f"В конце напиши ОБНОВЛЁННЫЙ блок для MEMORY.md:\n"
                f"```memory\n[обновлённый текст для вставки в MEMORY.md]\n```\n\n"
                f"Формат — краткий."
            )
        }]
    )

    reply = response.content[0].text

    # Извлечь блок memory из ответа и обновить MEMORY.md
    if "```memory" in reply:
        parts = reply.split("```memory")
        if len(parts) > 1:
            memory_block = parts[1].split("```")[0].strip()
            if memory_block and len(memory_block) > 50:
                update_memory(memory_block)
                reply += "\n\n✅ *MEMORY.md обновлён!*"

    save_note(f"🔒 Сессия закрыта")

    await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=collapse_menu())

# ─── /plan — План на сегодня ─────────────────────────────────────────────────

async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    existing_plan = get_today_plan()

    if existing_plan and "[Нет" not in existing_plan:
        await update.message.reply_text(
            f"📋 *План на {today()}:*\n\n{existing_plan[:3000]}",
            parse_mode="Markdown",
            reply_markup=collapse_menu()
        )
        return

    # Нет плана — создать через Claude
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=build_system_prompt(include_memory=True, include_plan=True),
        messages=[{
            "role": "user",
            "content": (
                f"Создай план дня на {today()} ({datetime.now().strftime('%A')}).\n"
                f"Используй данные из MEMORY.md (активные РП).\n\n"
                f"Формат:\n"
                f"# DayPlan — {today()}\n\n"
                f"## Фокус дня\n🎯 Главная: [задача из РП]\n\n"
                f"## Задачи\n1. [ ] ...\n2. [ ] ...\n3. [ ] ...\n\n"
                f"## Контекст\n- Неделя: {week_number()}\n- Блокеры: ...\n"
            )
        }]
    )

    plan_text = response.content[0].text
    save_day_plan(plan_text)

    await update.message.reply_text(
        f"📋 *План создан и сохранён!*\n\n{plan_text}",
        parse_mode="Markdown",
        reply_markup=collapse_menu()
    )

# ─── /review — Разбор заметок ────────────────────────────────────────────────

async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = get_notes()
    captures = get_today_captures()

    if not notes and not captures:
        await update.message.reply_text(
            "📭 Нет заметок для разбора. Напишите `. текст` чтобы добавить.",
            reply_markup=collapse_menu()
        )
        return

    content = ""
    if notes:
        content += f"**notes.md:**\n{notes[-2000:]}\n\n"
    if captures:
        content += f"**captures сегодня:**\n{captures[-1500:]}\n\n"

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system=build_system_prompt(include_memory=True),
        messages=[{
            "role": "user",
            "content": (
                f"Разбери заметки из inbox:\n\n{content}\n\n"
                f"Для каждой заметки определи:\n"
                f"- Тип (НЭП/Задача/Знание/Черновик/Идея/Личное/Шум)\n"
                f"- Действие (что сделать)\n\n"
                f"В конце дай сводку: сколько каждого типа, что приоритетно."
            )
        }]
    )

    await update.message.reply_text(
        f"🗂 *Разбор заметок:*\n\n{response.content[0].text}",
        parse_mode="Markdown",
        reply_markup=collapse_menu()
    )

# ─── /week — Недельное планирование ──────────────────────────────────────────

async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = get_memory()
    strategy = get_strategy()
    dissatisfactions = get_dissatisfactions()

    # Собрать архивные ревью
    archive_dir = os.path.join(DS_STRATEGY, "archive")
    latest_review = find_latest_file(archive_dir, "WeekReview-")
    review_text = read_file(latest_review) if latest_review else "[нет предыдущих ревью]"

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=build_system_prompt(include_memory=True, include_plan=True),
        messages=[{
            "role": "user",
            "content": (
                f"Проведи недельное планирование.\n\n"
                f"Стратегия:\n{strategy[:800] if strategy else '[не заполнена]'}\n\n"
                f"Неудовлетворённости:\n{dissatisfactions[:800] if dissatisfactions else '[не заполнены]'}\n\n"
                f"Прошлый обзор:\n{review_text[:800]}\n\n"
                f"Сделай ДВА блока:\n\n"
                f"БЛОК 1 — Итоги прошлой недели (если есть данные)\n\n"
                f"БЛОК 2 — WeekPlan на {week_number()}:\n"
                f"```weekplan\n"
                f"# WeekPlan — {week_number()}\n\n"
                f"## Цель недели\n[одно предложение]\n\n"
                f"## РП\n### РП1: [название] — P1\n- Результат: ...\n- Бюджет: ~ч\n\n"
                f"### РП2: ...\n### РП3: ...\n"
                f"```"
            )
        }]
    )

    reply = response.content[0].text

    # Извлечь и сохранить WeekPlan
    if "```weekplan" in reply:
        parts = reply.split("```weekplan")
        if len(parts) > 1:
            plan_block = parts[1].split("```")[0].strip()
            if plan_block and len(plan_block) > 30:
                save_week_plan(plan_block)
                reply += f"\n\n✅ *WeekPlan-{week_number()}.md сохранён!*"

    await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=collapse_menu())

# ─── Обработка кнопок ────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Свёрнутое меню → показать полное
    if data == "show_menu":
        await query.message.edit_reply_markup(reply_markup=main_menu())
        return

    # Перенаправить на соответствующие команды
    if data == "plan":
        # Создать фейковый Update для cmd_plan
        await _button_to_command(query, context, cmd_plan)
    elif data == "open":
        await _button_to_command(query, context, cmd_open)
    elif data == "close":
        await _button_to_command(query, context, cmd_close)
    elif data == "note_review":
        await _button_to_command(query, context, cmd_review)
    elif data == "week_review":
        await _button_to_command(query, context, cmd_week)
    elif data == "note":
        await query.message.reply_text(
            "✏️ Напишите заметку в формате:\n`. ваш текст`\n\nОна сохранится в `notes.md`",
            reply_markup=collapse_menu()
        )
    elif data == "task":
        context.user_data["mode"] = "new_task"
        await query.message.reply_text(
            "📌 *Новый РП*\nОпишите что хотите сделать.\n"
            "Я помогу сформулировать как РП (существительное, измеримый артефакт).",
            parse_mode="Markdown",
            reply_markup=collapse_menu()
        )
    elif data == "question":
        await query.message.reply_text(
            "❓ Напишите вопрос в формате:\n`? ваш вопрос`",
            reply_markup=collapse_menu()
        )
    elif data == "lesson":
        context.user_data["mode"] = "lesson"
        await query.message.reply_text(
            "💡 Опишите урок или инсайт. Я запишу его в captures.",
            reply_markup=collapse_menu()
        )

async def _button_to_command(query, context, handler):
    """Вызвать команду из кнопки, отправив ответ в тот же чат."""
    # Для кнопок делаем простой вызов через Claude
    # Создаём mock-update через reply
    class FakeMsg:
        def __init__(self, q):
            self.chat = q.message.chat
            self.reply_text = q.message.reply_text
            self.text = ""
    class FakeUpdate:
        def __init__(self, q):
            self.message = FakeMsg(q)
            self.effective_user = q.from_user

    await handler(FakeUpdate(query), context)

# ─── Обработка текстовых сообщений ──────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text or ""
    mode = context.user_data.get("mode")

    # 1. Быстрая заметка: ". текст"
    if text.startswith(".") and not text.startswith(".."):
        note_text = text[1:].strip()
        if not note_text:
            await msg.reply_text("Напишите после точки: `. ваша заметка`")
            return

        # Сохранить в notes.md
        save_note(note_text)

        # Классифицировать
        classification = await classify_note(note_text)

        # Сохранить capture с классификацией
        save_capture(note_text, classification)

        await msg.reply_text(
            f"✅ *Записано* [{now_str()}]\n\n"
            f"📝 `{note_text}`\n\n"
            f"📁 → `notes.md` + `capture-{today()}.md`\n\n"
            f"🗂 {classification}",
            parse_mode="Markdown",
            reply_markup=collapse_menu()
        )
        return

    # 2. Вопрос к базе: "? вопрос"
    if text.startswith("?"):
        question = text[1:].strip()
        if not question:
            await msg.reply_text("Напишите: `? ваш вопрос`")
            return

        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=build_system_prompt(include_memory=True),
            messages=[{"role": "user", "content": f"Вопрос: {question}"}]
        )
        await msg.reply_text(response.content[0].text, reply_markup=collapse_menu())
        return

    # 3. Режим "новый РП"
    if mode == "new_task":
        context.user_data.pop("mode", None)
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=build_system_prompt(include_memory=True),
            messages=[{
                "role": "user",
                "content": (
                    f"Пользователь хочет: «{text}»\n\n"
                    f"Сформулируй как РП (существительное, измеримый артефакт). "
                    f"Добавь: результат, бюджет времени, критерий готовности."
                )
            }]
        )
        # Сохранить как заметку-задачу
        save_note(f"📌 РП: {text}")
        save_capture(f"Новый РП: {text}", f"Тип: Задача\n{response.content[0].text}")

        await msg.reply_text(
            f"📌 *РП записан:*\n\n{response.content[0].text}\n\n"
            f"📁 → `notes.md` + `capture-{today()}.md`",
            parse_mode="Markdown",
            reply_markup=collapse_menu()
        )
        return

    # 4. Режим "урок"
    if mode == "lesson":
        context.user_data.pop("mode", None)
        save_note(f"💡 Урок: {text}")
        save_capture(text, "Тип: Знание\nКуда: memory/MEMORY.md или Pack\nДействие: формализовать")

        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=build_system_prompt(),
            messages=[{
                "role": "user",
                "content": f"Сформулируй урок одной строкой:\n«{text}»\nФормат: Урок: [суть]"
            }]
        )
        await msg.reply_text(
            f"💡 *Записано:*\n\n{response.content[0].text}\n\n"
            f"📁 → `notes.md` + `capture-{today()}.md`",
            parse_mode="Markdown",
            reply_markup=collapse_menu()
        )
        return

    # 5. Пересланное сообщение
    if msg.forward_date or msg.forward_from or msg.forward_from_chat:
        save_note(f"[Переслано] {text or '[медиа]'}")
        classification = await classify_note(text or "пересланное сообщение")
        save_capture(f"[Переслано] {text}", classification)

        await msg.reply_text(
            f"✅ *Переслано и записано* [{now_str()}]\n\n"
            f"📁 → `notes.md` + `capture-{today()}.md`\n\n"
            f"🗂 {classification}",
            parse_mode="Markdown",
            reply_markup=collapse_menu()
        )
        return

    # 6. Обычное сообщение — диалог с контекстом
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=build_system_prompt(include_memory=True, include_plan=True),
        messages=[{"role": "user", "content": text}]
    )
    await msg.reply_text(response.content[0].text, reply_markup=collapse_menu())

# ─── Регистрация и запуск ────────────────────────────────────────────────────

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

if __name__ == "__main__":
    ensure_dirs()
    print(f"🤖 IWE-бот запущен!")
    print(f"📁 Workspace: {WORKSPACE}")
    print(f"📁 DS-strategy: {DS_STRATEGY}")
    print(f"📁 Memory: {MEMORY_FILE}")
    app.run_polling()

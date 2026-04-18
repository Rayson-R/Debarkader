import os
import sqlite3
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import anthropic

# --- Config ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DB_PATH = "memory.db"

SYSTEM_PROMPT = """Ты — проектный ассистент floating home на Río Dulce, Гватемала.

ПРОЕКТ:
- Двухэтажный катамаран-стиль, 10.5×6.5м на двух стальных понтонах 12м (4мм лист)
- Первый этаж: открытый, кухонный остров, гостевая зона
- Второй этаж: рубка/кокпит (6×6м), две спальни
- Остекление рубки: поликарбонат 6–8мм, передние окна 20° от вертикали (наклон вперёд), боковые 10°, угловые панели 45°
- Кровля: солнечные панели TOPCon N-type ~26–28кВт пик, двускатная, сбор дождевой воды
- Пропульсия: два кормовых электромотора, дизель-генератор в понтоне
- Авиаплатформа: трамплин-стиль на корме второго этажа, ~2.5–3м вынос, для EHang EH216-S
- Ветер: VAWT турбины с защитой от шквалов через dump load контроллеры
- Строительство: Mar Marine Yacht Club, поставщик поликарбоната AILAMPO (CA-9)

УЧАСТНИКИ:
- Владелец/координатор: главный по решениям
- Архитектор: надстройка
- Морской инженер: расчёты понтонов и нагрузок
- AILAMPO: поликарбонат и изготовление

ТВОЯ РОЛЬ:
- Отвечай на технические вопросы по проекту
- Помни контекст разговора
- В групповом чате — отвечай когда упоминают @бота или отвечают на твои сообщения
- Будь конкретным, техническим, без лишней воды
- Язык ответа — тот же что и вопрос (русский, испанский, английский)
"""

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_history(chat_id: int, limit: int = 20) -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def save_message(chat_id: int, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, role, content)
    )
    conn.commit()
    conn.close()

def clear_history(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# --- Claude ---
def ask_claude(chat_id: int, user_message: str) -> str:
    save_message(chat_id, "user", user_message)
    history = get_history(chat_id)
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history
    )
    
    reply = response.content[0].text
    save_message(chat_id, "assistant", reply)
    return reply

# --- Handlers ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    chat_id = message.chat_id
    text = message.text
    bot_username = context.bot.username

    # В группе — отвечаем только если упомянули бота или ответили на его сообщение
    if message.chat.type in ["group", "supergroup"]:
        is_mentioned = f"@{bot_username}" in text
        is_reply_to_bot = (
            message.reply_to_message and
            message.reply_to_message.from_user.username == bot_username
        )
        if not is_mentioned and not is_reply_to_bot:
            return
        # Убираем упоминание из текста
        text = text.replace(f"@{bot_username}", "").strip()

    if not text:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        reply = ask_claude(chat_id, text)
        await message.reply_text(reply)
    except Exception as e:
        await message.reply_text(f"Ошибка: {str(e)}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я ассистент проекта floating home на Río Dulce.\n"
        "Спрашивай о проекте — отвечу по контексту.\n"
        "В группе — упомяни меня через @"
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.message.chat_id)
    await update.message.reply_text("История очищена.")

# --- Main ---
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    print("Бот запущен...")
    app.run_polling()

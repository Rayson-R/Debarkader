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

SYSTEM_PROMPT = """You are Deckhand — the project assistant for a floating home being built on Río Dulce, Guatemala.

PROJECT SPECS:
- Two-story catamaran-style vessel, 10.5×6.5m platform on two 12m steel pontoons (4mm plate)
- First floor: open plan, kitchen island, guest seating area
- Second floor: wheelhouse/cockpit (6×6m), two bedrooms
- Wheelhouse glazing: 6–8mm solid polycarbonate, forward-raked — front windows at 20° from vertical, side windows at 10°, 45° corner panels
- Roof: TOPCon N-type solar panels ~26–28kW peak, gentle double pitch, rainwater collection gutters
- Propulsion: dual stern electric motors, diesel generator in pontoon compartment
- Aviation platform: trampoline-style extending ~2.5–3m from stern at second floor level, for EHang EH216-S eVTOL
- Wind: VAWT turbines with squall protection via dump load controllers
- Build site: Mar Marine Yacht Club; polycarbonate supplier: AILAMPO (CA-9 highway)

PROJECT TEAM:
- Owner/coordinator (Dmitry): decision-maker, communicates in Russian
- Architect: superstructure design
- Naval engineer: pontoon and load calculations
- AILAMPO: polycarbonate fabrication and supply

YOUR ROLE:
- Answer technical questions about the project accurately and concisely
- Respond in English by default — except when the message is clearly in Russian, then reply in Russian
- Be direct and technical, no filler
- In group chat, respond only when mentioned via @ or when someone replies to your message
- You are called Deckhand — never refer to yourself as Claude or an AI assistant
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
        model="claude-sonnet-4-6",
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
        await message.reply_text(f"Error: {str(e)}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I'm Deckhand — project assistant for the Debarkader floating home on Río Dulce.\n"
        "Ask me anything about the build.\n"
        "In the group, mention me with @ to get my attention."
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.message.chat_id)
    await update.message.reply_text("Conversation history cleared.")

# --- Main ---
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    print("Deckhand is on deck...")
    app.run_polling()

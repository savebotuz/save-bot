import time
import os
import asyncio
import sqlite3
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai

# ---------- SOZLAMALAR ----------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.8-flash"
DB_NAME = "savebot.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN sozlanmagan!")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY sozlanmagan!")

ai_client = genai.Client(api_key=GEMINI_API_KEY)
chat_history = {}


# ---------- MA'LUMOTLAR BAZASI ----------

def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS saved_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                content TEXT,
                file_id TEXT,
                created_at TEXT NOT NULL
            )
        """)


def save_item(user_id, item_type, content=None, file_id=None):
    with sqlite3.connect(DB_NAME) as db:
        db.execute(
            """
            INSERT INTO saved_items
            (user_id, item_type, content, file_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                item_type,
                content,
                file_id,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )


# ---------- /start ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Assalomu alaykum! Save Bot'ga xush kelibsiz!\n\n"
        "Men sizga quyidagilarda yordam beraman:\n"
        "🤖 Sun'iy intellekt bilan suhbat\n"
        "🌐 Tarjima va til o'rganish\n"
        "📚 Darslar va konspektlar\n"
        "💡 G'oyalar va matn yozish\n"
        "📁 Matn, rasm, video va hujjatlarni saqlash\n\n"
        "Buyruqlar:\n"
        "/save matn — matnni saqlash\n"
        "/saved — saqlanganlarni ko'rish\n"
        "/clear — suhbat tarixini tozalash\n"
        "/help — yordam"
    )
    await update.effective_message.reply_text(text)


# ---------- /help ----------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ---------- MATN SAQLASH ----------

async def save_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    text = " ".join(context.args).strip()

    if not text:
        await message.reply_text(
            "Saqlamoqchi bo'lgan matningizni buyruqdan keyin yozing.\n\n"
            "Masalan:\n/save Ertaga tarixdan seminar bor"
        )
        return

    save_item(
        update.effective_user.id,
        "text",
        content=text,
    )
    await message.reply_text("✅ Matningiz saqlandi!")


# ---------- RASM, VIDEO VA HUJJATLAR ----------

async def save_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id

    if message.photo:
        item_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        item_type = "video"
        file_id = message.video.file_id
    elif message.document:
        item_type = "document"
        file_id = message.document.file_id
    else:
        return

    caption = message.caption or ""

    save_item(
        user_id,
        item_type,
        content=caption,
        file_id=file_id,
    )

    await message.reply_text(
        "✅ Faylingiz saqlandi!\n"
        "Uni keyin /saved buyrug'i orqali ko'rishingiz mumkin."
    )


# ---------- /saved ----------

async def saved_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute(
            """
            SELECT item_type, content, file_id, created_at
            FROM saved_items
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    if not rows:
        await update.effective_message.reply_text(
            "📂 Hozircha saqlangan narsalar yo'q."
        )
        return

    await update.effective_message.reply_text(
        f"📁 Oxirgi {len(rows)} ta saqlangan yozuvingiz:"
    )

    for item_type, content, file_id, created_at in reversed(rows):
        try:
            if item_type == "text":
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📝 {content}\n🕒 {created_at}",
                )

            elif item_type == "photo":
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=file_id,
                    caption=content or None,
                )

            elif item_type == "video":
                await context.bot.send_video(
                    chat_id=user_id,
                    video=file_id,
                    caption=content or None,
                )

            elif item_type == "document":
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file_id,
                    caption=content or None,
                )

        except Exception:
            logging.exception("Saqlangan faylni yuborishda xatolik")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Bir faylni qayta yuborib bo'lmadi. Sana: {created_at}",
            )


# ---------- /clear ----------

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_history.pop(user_id, None)

    await update.effective_message.reply_text(
        "🧹 AI suhbat tarixingiz tozalandi.\n"
        "Saqlangan matn va fayllaringiz o'chirilmadi."
    )


# ---------- SUN'IY INTELLEKT ----------

async def ask_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id
    user_text = message.text.strip()

    if not user_text:
        return

    history = chat_history.setdefault(user_id, [])
    history.append(f"Foydalanuvchi: {user_text}")
    history[:] = history[-10:]

    prompt = (
        "Sen Save Bot nomli foydali AI yordamchisisan. "
        "Foydalanuvchiga o'zbek tilida, sodda va aniq javob ber. "
        "Agar foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber. "
        "Tarjima, ta'lim, tarix, yozish va kundalik savollarda yordam ber.\n\n"
        + "\n".join(history)
        + "\nYordamchi:"
    )

    await message.reply_text("🤔 Javob tayyorlayapman...")

    try:
       from google.genai.errors import ServerError

for attempt in range(3):
    try:
      
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=MODEL_NAME,
                contents=prompt
            ),
            timeout=9
        )

        answer = (
            response.text
            if response and response.text
            else "Kechirasiz, javob tayyorlanmadi."
        )

        history.append(f"Yordamchi: {answer}")
        history[:] = history[-10:]

        for i in range(0, len(answer), 4000):
            await message.reply_text(answer[i:i + 4000])

    except asyncio.TimeoutError:
        await message.reply_text(
            "⏳ AI hozir sekin ishlayapti. "
            "Iltimos, savolingizni qayta yuboring."
        )

    except Exception:
        logging.exception("Gemini API xatoligi")
        await message.reply_text(
            "⚠️ Hozir javob olishda xatolik yuz berdi. "
            "Birozdan so'ng qayta urinib ko'ring."
        )

# ---------- RENDER WEB SERVICE UCHUN ----------

async def health_server(reader, writer):
    try:
        await reader.read(4096)
        body = b"Save Bot is running"
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        writer.write(response)
        await writer.drain()
    except Exception:
        logging.exception("Health server xatoligi")
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("save", save_text))
    app.add_handler(CommandHandler("saved", saved_items))
    app.add_handler(CommandHandler("clear", clear_history))

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            save_media,
        )
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ask_ai)
    )

    await app.initialize()
    await app.start()

    if app.updater is None:
        raise RuntimeError("Telegram updater ishga tushmadi!")

    await app.updater.start_polling(drop_pending_updates=False)

    port = int(os.environ.get("PORT", "10000"))
    server = await asyncio.start_server(
        health_server,
        host="0.0.0.0",
        port=port,
    )

    logging.info("Save Bot ishga tushdi. Port: %s", port)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Save Bot to'xtatildi.")

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone

from google import genai
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# SOZLAMALAR
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = "gemini-3.8-flash"
DATABASE = "savebot.db"
AI_TIMEOUT = 8.5
MAX_HISTORY = 10
MAX_OUTPUT_CHARS = 3900

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN sozlanmagan.")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY sozlanmagan.")

client = genai.Client(api_key=GEMINI_API_KEY)
chat_history = {}


# =========================
# MA'LUMOTLAR BAZASI
# =========================

def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS saved_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                content TEXT,
                file_id TEXT,
                created_at TEXT NOT NULL
            )
        """)
        db.commit()


def save_item(user_id, kind, content=None, file_id=None):
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DATABASE) as db:
        db.execute(
            """
            INSERT INTO saved_items
                (user_id, kind, content, file_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, kind, content, file_id, created_at),
        )
        db.commit()


def get_saved_items(user_id, limit=10):
    with sqlite3.connect(DATABASE) as db:
        return db.execute(
            """
            SELECT id, kind, content, file_id, created_at
            FROM saved_items
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()


# =========================
# BUYRUQLAR
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 Assalomu alaykum! Men Save Bot.\n\n"
        "🤖 Savol yozing — AI javob beradi.\n"
        "🌐 Tarjima va darslarda yordam beraman.\n"
        "💾 Matn yoki fayllarni saqlayman.\n\n"
        "Buyruqlar:\n"
        "/save matn — matnni saqlash\n"
        "/saved — saqlanganlarni ko‘rish\n"
        "/clear — saqlanganlarni o‘chirish\n"
        "/help — yordam"
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_message.reply_text(
        "📚 Save Bot yordami\n\n"
        "• Istalgan savolingizni yozing.\n"
        "• /save matn — matnni saqlaydi.\n"
        "• /saved — oxirgi 10 ta saqlangan narsani ko‘rsatadi.\n"
        "• Rasm, video va hujjat yuborsangiz, ular saqlanadi.\n"
        "• /clear — saqlangan narsalarni o‘chiradi."
    )


async def save_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user

    text = " ".join(context.args).strip()

    if not text and message.reply_to_message:
        replied = message.reply_to_message
        text = replied.text or replied.caption or ""

    if not text:
        await message.reply_text(
            "Saqlash uchun matn yozing:\n/save Kerakli matn"
        )
        return

    save_item(user.id, "text", content=text)
    await message.reply_text("✅ Matn saqlandi!")


async def show_saved(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    items = get_saved_items(user.id)

    if not items:
        await message.reply_text("📭 Hozircha saqlangan narsalar yo‘q.")
        return

    await message.reply_text("📂 Oxirgi saqlangan narsalaringiz:")

    for item_id, kind, content, file_id, created_at in reversed(items):
        try:
            if kind == "text":
                text = (content or "")[:3500]
                await message.reply_text(f"📝 {text}")
            elif kind == "photo":
                await message.reply_photo(
                    file_id, caption=(content or "🖼 Saqlangan rasm")[:1000]
                )
            elif kind == "video":
                await message.reply_video(
                    file_id, caption=(content or "🎬 Saqlangan video")[:1000]
                )
            elif kind == "document":
                await message.reply_document(
                    file_id, caption=(content or "📄 Saqlangan hujjat")[:1000]
                )
            elif kind == "audio":
                await message.reply_audio(file_id)
            elif kind == "voice":
                await message.reply_voice(file_id)
        except TelegramError:
            logging.exception("Saqlangan elementni yuborib bo‘lmadi: %s", item_id)
            await message.reply_text(
                f"⚠️ {item_id}-elementni yuborib bo‘lmadi."
            )


async def clear_saved(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    with sqlite3.connect(DATABASE) as db:
        db.execute(
            "DELETE FROM saved_items WHERE user_id = ?", (user_id,)
        )
        db.commit()

    chat_history.pop(user_id, None)
    await update.effective_message.reply_text(
        "🗑 Saqlangan narsalaringiz o‘chirildi."
    )


# =========================
# RASM VA FAYLLARNI SAQLASH
# =========================

async def save_media(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user

    if message.photo:
        kind = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        kind = "video"
        file_id = message.video.file_id
    elif message.document:
        kind = "document"
        file_id = message.document.file_id
    elif message.audio:
        kind = "audio"
        file_id = message.audio.file_id
    elif message.voice:
        kind = "voice"
        file_id = message.voice.file_id
    else:
        return

    caption = message.caption or ""
    save_item(user.id, kind, content=caption, file_id=file_id)
    await message.reply_text("💾 Fayl saqlandi! /saved orqali ko‘rishingiz mumkin.")


# =========================
# GEMINI AI
# =========================

def generate_ai_answer(prompt):
    return client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )


async def ai_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    user_text = (message.text or "").strip()

    if not user_text:
        return

    history = chat_history.setdefault(user.id, [])
    history.append(f"Foydalanuvchi: {user_text}")
    history[:] = history[-MAX_HISTORY:]

    prompt = (
        "Sen Save Bot nomli foydali AI yordamchisisan. "
        "Odatda o‘zbek tilida sodda, aniq va foydali javob ber. "
        "Foydalanuvchi boshqa tilda yozsa, o‘sha tilda javob ber. "
        "Tarjima, ta’lim, tarix, yozish va kundalik savollarda yordam ber. "
        "Keraksiz uzun kirish so‘zlarini ishlatma.\n\n"
        + "\n".join(history)
        + "\nYordamchi:"
    )

    status = await message.reply_text("🤔 Savolingizni ko‘rib chiqyapman...")

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(generate_ai_answer, prompt),
            timeout=AI_TIMEOUT,
        )

        answer = (
            (response.text or "").strip()
            if response else ""
        )

        if not answer:
            answer = "Kechirasiz, hozir javob tayyorlay olmadim."

        history.append(f"Yordamchi: {answer}")
        history[:] = history[-MAX_HISTORY:]

        try:
            await status.delete()
        except TelegramError:
            pass

        for index in range(0, len(answer), MAX_OUTPUT_CHARS):
            await message.reply_text(
                answer[index:index + MAX_OUTPUT_CHARS]
            )

    except asyncio.TimeoutError:
        await status.edit_text(
            "⏳ AI javobi 9 soniyada kelmadi. "
            "Iltimos, savolingizni yana bir marta yuboring."
        )

    except Exception:
        logging.exception("Gemini API xatoligi")
        await status.edit_text(
            "⚠️ AI xizmatida vaqtinchalik xatolik yuz berdi. "
            "Birozdan so‘ng qayta urinib ko‘ring."
        )


# =========================
# RENDER HEALTH CHECK
# =========================

async def health_check(reader, writer):
    try:
        await asyncio.wait_for(reader.readline(), timeout=2)

        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            if line in (b"\r\n", b"\n", b""):
                break

        body = b"Save Bot is running"
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# =========================
# ISHGA TUSHIRISH
# =========================

async def main():
    init_db()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("save", save_text))
    application.add_handler(CommandHandler("saved", show_saved))
    application.add_handler(CommandHandler("clear", clear_saved))

    media_filter = (
        filters.PHOTO
        | filters.VIDEO
        | filters.Document.ALL
        | filters.AUDIO
        | filters.VOICE
    )
    application.add_handler(MessageHandler(media_filter, save_media))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat)
    )

    port = int(os.getenv("PORT", "10000"))
    server = await asyncio.start_server(
        health_check, host="0.0.0.0", port=port
    )

    logging.info("Health server %s-portda ishga tushdi.", port)

    try:
        async with application:
            await application.start()

            if application.updater is None:
                raise RuntimeError("Telegram updater ishga tushmadi.")

            await application.updater.start_polling()
            logging.info("Save Bot ishga tushdi.")

            async with server:
                await asyncio.Event().wait()

    finally:
        server.close()
        await server.wait_closed()

        if application.updater and application.updater.running:
            await application.updater.stop()

        if application.running:
            await application.stop()

        logging.info("Save Bot to‘xtatildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Dastur to‘xtatildi.")

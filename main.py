
import os
import sqlite3
import asyncio
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai

# ---------- SOZLAMALAR ----------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "savebot.db"
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Har bir foydalanuvchi uchun suhbat tarixi
histories = {}


# ---------- MA'LUMOTLAR BAZASI ----------

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS saved_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def save_item(user_id, item_type, content):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """INSERT INTO saved_items
               (user_id, item_type, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                user_id,
                item_type,
                content,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )


def get_saved_items(user_id):
    with sqlite3.connect(DB_PATH) as db:
        return db.execute(
            """SELECT id, item_type, content, created_at
               FROM saved_items
               WHERE user_id = ?
               ORDER BY id DESC LIMIT 10""",
            (user_id,),
        ).fetchall()


# ---------- /START ----------

WELCOME = (
    "Salom! 👋 Save Bot'ga xush kelibsiz!\n\n"
    "💙 Men sizning aqlli yordamchingizman.\n\n"
    "🤖 Nimalarda yordam beraman?\n"
    "💬 Savollarga javob berish\n"
    "🌐 O‘zbekcha, ruscha va inglizcha tarjima\n"
    "📚 Dars va uy vazifalarida yordam\n"
    "✍️ Matn, insho va xabarlar yozish\n"
    "💡 G‘oyalar va maslahatlar\n\n"
    "📁 Rasm, video va hujjatlarni saqlash\n"
    "📝 Muhim matnlarni saqlash\n"
    "📂 /saved — saqlanganlaringizni ko‘rish\n"
    "💾 /save matn — matnni saqlash\n"
    "ℹ️ /help — yordam\n\n"
    "✨ Boshlash uchun menga savolingizni yozing!"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 Save Bot yo‘riqnomasi\n\n"
        "• Istalgan savolingizni yozing — AI javob beradi.\n"
        "• Rasm, video yoki hujjat yuboring — saqlanadi.\n"
        "• /save Muhim ma'lumot — matnni saqlaydi.\n"
        "• /saved — oxirgi 10 ta saqlangan yozuvni ko‘rsatadi.\n"
        "• /clear — AI suhbat tarixini tozalaydi.\n\n"
        "Bot o‘zbekcha, ruscha va inglizcha ishlashga mo‘ljallangan."
    )


# ---------- MATN SAQLASH ----------

async def save_text_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "Saqlash uchun matn kiriting:\n/save Muhim ma'lumot"
        )
        return

    save_item(update.effective_user.id, "Matn", text)
    await update.message.reply_text("✅ Matningiz saqlandi!")


async def saved_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    items = get_saved_items(update.effective_user.id)

    if not items:
        await update.message.reply_text(
            "📂 Hozircha saqlangan ma'lumotlar yo‘q."
        )
        return

    lines = ["📂 Oxirgi saqlangan ma'lumotlaringiz:\n"]

    for item_id, kind, content, created in items:
        preview = content.replace("\n", " ")
        if len(preview) > 180:
            preview = preview[:180] + "..."

        lines.append(
            f"#{item_id} | {kind} | {created}\n{preview}"
        )

    await update.message.reply_text("\n\n".join(lines))


async def clear_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    histories.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "🧹 AI bilan suhbat tarixi tozalandi. "
        "Saqlangan fayllaringiz o‘chmadi."
    )


# ---------- RASM, VIDEO VA HUJJATLAR ----------

async def media_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    message = update.message
    user_id = update.effective_user.id

    if message.photo:
        file_id = message.photo[-1].file_id
        kind = "Rasm"
    elif message.video:
        file_id = message.video.file_id
        kind = "Video"
    elif message.document:
        file_id = message.document.file_id
        kind = "Hujjat"
    else:
        return

    caption = message.caption or ""
    content = f"file_id={file_id}; izoh={caption}"

    save_item(user_id, kind, content)

    await message.reply_text(
        f"✅ {kind} saqlandi!\n"
        "Qayta ko‘rish uchun /saved buyrug‘ini yuboring."
    )


# ---------- SUN'IY INTELLEKT ----------

async def ai_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    user_text = update.message.text.strip()

    # Oddiy xabarlar ham saqlanadi
    save_item(user_id, "Foydalanuvchi xabari", user_text)

    if not ai_client:
        await update.message.reply_text(
            "⚠️ AI hali sozlanmagan. "
            "Administrator Gemini API kalitini ulashi kerak."
        )
        return

    history = histories.setdefault(user_id, [])
    history.append({"role": "user", "text": user_text})

    # Juda uzun tarixni cheklash
    history[:] = history[-12:]

    prompt = (
        "Sen Save Bot nomli foydali, xushmuomala AI yordamchisan. "
        "O‘zbek, rus va ingliz tillarini tushunasan. "
        "Foydalanuvchi qaysi tilda yozsa, odatda shu tilda javob ber. "
        "Savollarga aniq, tushunarli va xavfsiz javob ber. "
        "Bilmagan narsangni to‘qib chiqarmagin.\n\n"
    )

    for item in history:
        role = "Foydalanuvchi" if item["role"] == "user" else "Save Bot"
        prompt += f"{role}: {item['text']}\n"

    try:
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
        )

        answer = response.text or "Kechirasiz, javob tayyorlay olmadim."
        history.append({"role": "model", "text": answer})
        history[:] = history[-12:]

        # Telegram xabar uzunligi chegarasiga moslash
        for start_index in range(0, len(answer), 4000):
            await update.message.reply_text(
                answer[start_index:start_index + 4000]
            )

    except Exception:
        logger.exception("AI javobida xatolik")
        await update.message.reply_text(
            "⚠️ Hozir javob berishda xatolik yuz berdi. "
            "Birozdan so‘ng qayta urinib ko‘ring."
        )


# ---------- BOTNI ISHGA TUSHIRISH ----------

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN sozlanmagan.")

    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("save", save_text_command))
    app.add_handler(CommandHandler("saved", saved_command))
    app.add_handler(CommandHandler("clear", clear_command))

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            media_handler,
        )
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_handler)
    )

    logger.info("Save Bot ishga tushmoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()

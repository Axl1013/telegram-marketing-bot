import os
from dotenv import load_dotenv
import logging
import nest_asyncio
import asyncio
import openai
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from flask import Flask
from threading import Thread
from PIL import Image
from io import BytesIO

# 🖼️ Logo-bestand (zorg dat dit 'logo.png' in dezelfde folder staat)
LOGO_PATH = "logo.png"

# 🔑 API-sleutels invullen
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("JOUW_TELEGRAM_BOT_TOKEN")
load_dotenv()
OPENAI_API_KEY = os.getenv("JOUW_OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY
nest_asyncio.apply()

app = Flask('')

@app.route('/')
def home():
    return "✅ Telegram bot is actief!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.caption:
        await update.message.reply_text("⚠️ Stuur een foto met een promotietekst in het bijschrift.")
        return

    promo_text = update.message.caption
    prompt = f"Schrijf een aantrekkelijke Instagram-post op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe."

    try:
        # AI-caption genereren
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        ai_text = response.choices[0].message.content.strip()

        # Foto verwerken
        photo = update.message.photo[-1]
        file = await photo.get_file()
        file_bytes = await file.download_as_bytearray()
        original = Image.open(BytesIO(file_bytes)).convert("RGBA")

        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = logo.resize((original.width // 2, int(original.height // 10)))

        position = (
            original.width - logo.width - 10,
            original.height - logo.height - 10
        )
        original.paste(logo, position, logo)

        final_path = "final_image.png"
        original.save(final_path)

        with open(final_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"📢 *Instagram Post Idee:*\n\n{ai_text}",
                parse_mode="Markdown"
            )

    except Exception as e:
        logging.error(f"Fout: {str(e)}")
        await update.message.reply_text(f"❌ Er ging iets mis:\n{str(e)}")

async def main():
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.PHOTO & filters.Caption(), handle_message))
    logging.info("✅ Bot gestart...")
    await bot_app.run_polling()

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())

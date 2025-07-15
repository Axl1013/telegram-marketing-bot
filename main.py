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
import json
from datetime import datetime
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# 🖼️ Logo-bestand (zorg dat dit 'logo.png' in dezelfde folder staat)
LOGO_PATH = "logo.png"

# 🔑 API-sleutels invullen
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("JOUW_TELEGRAM_BOT_TOKEN")
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

def save_scheduled_post(data):
    if not os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "w") as f:
            json.dump([], f)

    with open(SCHEDULE_FILE, "r") as f:
        posts = json.load(f)

    posts.append(data)

    with open(SCHEDULE_FILE, "w") as f:
        json.dump(posts, f, indent=2)


logging.basicConfig(level=logging.INFO)

# Tijdelijke opslag voor per-gebruiker geplande content
user_context = {}
SCHEDULE_FILE = "scheduled_posts.json"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.caption:
        await update.message.reply_text("⚠️ Stuur een foto met een promotietekst in het bijschrift.")
        return

    promo_text = update.message.caption
    # Controleren of de tekst een prijs of promotie bevat (bijvoorbeeld door het zoeken naar woorden zoals "korting", "aanbieding", "prijs", etc.)
    price_keywords = ["korting", "aanbieding", "prijs", "actie", "promo"]
    if any(keyword in promo_text.lower() for keyword in price_keywords):
        prompt = f"Schrijf een aantrekkelijke Instagram-post in het Nederlands op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe en maak het promotioneel, inclusief een prijs of korting."
    else:
        prompt = f"Schrijf een aantrekkelijke Instagram-post in het Nederlands op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe, zonder een prijs of promotie toe te voegen."

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

        # Sla de info op in tijdelijke context
        user_id = update.effective_user.id
        user_context[user_id] = {
            "image_path": final_path,
            "caption": ai_text,
            "chat_id": update.effective_chat.id
        }

        # Verstuur de gegenereerde afbeelding en bijschrift terug naar de gebruiker
        with open(final_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"📢 *Instagram Post Idee:*\n\n{ai_text}",
                parse_mode="Markdown"
            )

        # Vraag de gebruiker om het tijdstip van de post
        await update.message.reply_text(
            "🕒 Wanneer wil je dat deze post op Instagram geplaatst wordt?\n"
            "Stuur een tijd in dit formaat: `DD-MM-YYYY HH:MM` (bijv. `17-07-2025 14:30`)",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Fout: {str(e)}")
        await update.message.reply_text(f"❌ Er ging iets mis:\n{str(e)}")



async def handle_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_context:
        await update.message.reply_text("⚠️ Er is geen gegenereerde post om te plannen. Stuur eerst een afbeelding met bijschrift.")
        return

    try:
        text = update.message.text.strip()
        post_time = datetime.strptime(text, "%d-%m-%Y %H:%M")
        post_data = user_context[user_id]
        post_data["post_time"] = post_time.strftime("%Y-%m-%d %H:%M")

        save_scheduled_post(post_data)
        del user_context[user_id]

        await update.message.reply_text(
            f"✅ Post gepland voor {post_time.strftime('%d-%m-%Y %H:%M')}!\n"
            f"Ik post dit automatisch zodra Instagram-koppeling is ingesteld. 😉"
        )

    except ValueError:
        await update.message.reply_text("❌ Ongeldig formaat. Gebruik `DD-MM-YYYY HH:MM` (bijv. `17-07-2025 14:30`).")


async def main():
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.PHOTO & filters.Caption(), handle_message))
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_schedule_time))
    logging.info("✅ Bot gestart...")
    await bot_app.run_polling()
if __name__ == "__main__":
    keep_alive()
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())



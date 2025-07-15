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
from instagrapi import Client
from instagrapi.exceptions import *
from apscheduler.schedulers.background import BackgroundScheduler

# 🖼️ Logo-bestand
LOGO_PATH = "logo.png"

# 🔑 Laad API-sleutels
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("JOUW_TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("JOUW_OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY
nest_asyncio.apply()

# 🌐 Flask-setup
app = Flask('')
@app.route('/')
def home():
    return "✅ Telegram bot is actief!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# 🧠 Logging
logging.basicConfig(level=logging.INFO)

# 📦 Context opslag
user_context = {}
SCHEDULE_FILE = "scheduled_posts.json"

# 📸 Instagram login en sessiebeheer
def login_and_save_session():
    cl = Client()
    cl.login("marketingbotasmr", "Kimvg001")
    cl.dump_settings("insta_session.json")

def get_instagram_client():
    cl = Client()
    if os.path.exists("insta_session.json"):
        cl.load_settings("insta_session.json")
    else:
        login_and_save_session()
        cl.load_settings("insta_session.json")
    return cl

def post_on_instagram(image_path, caption):
    try:
        cl = get_instagram_client()
        cl.photo_upload(image_path, caption)
        print(f"✅ Post geplaatst op Instagram met caption: {caption}")
    except Exception as e:
        print(f"❌ Fout bij posten: {e}")

# 🗓️ Planning
scheduler = BackgroundScheduler()
scheduler.start()

def schedule_post(image_path, caption, post_time):
    scheduled_time = datetime.strptime(post_time, "%d-%m-%Y %H:%M")
    time_diff = (scheduled_time - datetime.now()).total_seconds()
    if time_diff > 0:
        scheduler.add_job(post_on_instagram, 'date', run_date=scheduled_time, args=[image_path, caption])
        print(f"📅 Post gepland voor {post_time}")
    else:
        print("⛔ Tijd ligt in het verleden")

def save_scheduled_post(data):
    if not os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "w") as f:
            json.dump([], f)
    with open(SCHEDULE_FILE, "r") as f:
        posts = json.load(f)
    posts.append(data)
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(posts, f, indent=2)

# 🤖 Telegram handlers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.caption:
        await update.message.reply_text("⚠️ Stuur een foto met een promotietekst in het bijschrift.")
        return

    promo_text = update.message.caption
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

        # Foto ophalen van Telegram
        photo = update.message.photo[-1]
        file = await photo.get_file()
        file_bytes = await file.download_as_bytearray()
        original = Image.open(BytesIO(file_bytes)).convert("RGBA")

        # Logo laden en toevoegen
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = logo.resize((original.width // 2, int(original.height // 10)))

        position = (
            original.width - logo.width - 20,
            original.height - logo.height - 250
        )
        original.paste(logo, position, logo)

        # Afbeelding opslaan
        final_path = "final_image.png"
        original.save(final_path)

        # AI-caption + afbeelding terugsturen naar gebruiker
        with open(final_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"📢 *Instagram Post Idee:*\n\n{ai_text}",
                parse_mode="Markdown"
            )

        # Opslaan in context om later te plannen
        user_id = update.effective_user.id
        user_context[user_id] = {
            "image_path": final_path,
            "caption": ai_text,
            "chat_id": update.effective_chat.id
        }

        # Vraag tijdstip voor Instagram post
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
        await update.message.reply_text("⚠️ Geen gegenereerde post om te plannen. Stuur eerst een afbeelding met bijschrift.")
        return

    try:
        text = update.message.text.strip()
        post_time = datetime.strptime(text, "%d-%m-%Y %H:%M")
        post_data = user_context[user_id]
        post_data["post_time"] = post_time.strftime("%d-%m-%Y %H:%M")

        save_scheduled_post(post_data)
        schedule_post(post_data["image_path"], post_data["caption"], post_data["post_time"])
        del user_context[user_id]

        await update.message.reply_text(
            f"✅ Post gepland voor {post_time.strftime('%d-%m-%Y %H:%M')}!"
        )

    except ValueError:
        await update.message.reply_text("❌ Ongeldig formaat. Gebruik `DD-MM-YYYY HH:MM`.")

async def main():
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.PHOTO & filters.Caption(), handle_message))
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_schedule_time))
    logging.info("✅ Bot gestart...")
    await bot_app.run_polling()

if __name__ == "__main__":
    keep_alive()
    login_and_save_session()
    asyncio.run(main())

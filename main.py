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
import time
from apscheduler.schedulers.background import BackgroundScheduler

def login_and_save_session():
    cl = Client()
    cl.login("marketingbotasmr", "Kimvg001")
    cl.dump_settings("insta_session.json")  # sla sessie op

def load_saved_session():
    cl = Client()
    cl.load_settings("insta_session.json")
    cl.login("jouw_gebruikersnaam", "jouw_wachtwoord")
    return cl
def login_to_instagram():
    cl = Client()

    # Voer je gebruikersnaam en wachtwoord in
    username = "marketingbotasmr"
    password = "Kimvg001"

    try:
        # Log in op Instagram
        cl.login(username, password)

        # Haal gebruikersinformatie op om te controleren of de login succesvol is
        user_info = cl.user_info(cl.user_id)
        print(f"Login succesvol! Gebruiker: {user_info.username}")
        return cl
    except Exception as e:
        print(f"Fout bij inloggen: {e}")
        return None

# Test of de login werkt
login_to_instagram()
# Functie om een foto te posten
def post_on_instagram(image_path, caption, cl):
    try:
        cl.photo_upload(image_path, caption)  # Upload de foto naar Instagram
        print(f"Post succesvol gepost op Instagram met caption: {caption}")
    except Exception as e:
        print(f"Er ging iets mis bij het plaatsen van de post: {e}")

# Functie om de post te plannen op de opgegeven tijd
def schedule_post(image_path, caption, post_time):
    # Zet de geplande tijd om naar een datetime object
    scheduled_time = datetime.strptime(post_time, "%d-%m-%Y %H:%M")

    # Bereken het aantal seconden tussen nu en de geplande tijd
    time_diff = (scheduled_time - datetime.now()).total_seconds()

    if time_diff > 0:
        # Start de scheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(post_on_instagram, 'date', run_date=scheduled_time, args=[image_path, caption, cl])
        scheduler.start()
        print(f"Post is gepland om {post_time}.")
    else:
        print(f"De opgegeven tijd ({post_time}) is in het verleden!")


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
    price_keywords = ["korting", "aanbieding", "prijs", "actie", "promo"]
    if any(keyword in promo_text.lower() for keyword in price_keywords):
        prompt = f"Schrijf een aantrekkelijke Instagram-post in het Nederlands op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe en maak het promotioneel, inclusief een prijs of korting."
    else:
        prompt = f"Schrijf een aantrekkelijke Instagram-post in het Nederlands op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe, zonder een prijs of promotie toe te voegen."

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        ai_text = response.choices[0].message.content.strip()

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

        user_id = update.effective_user.id
        user_context[user_id] = {
            "image_path": final_path,
            "caption": ai_text,
            "chat_id": update.effective_chat.id
        }

        with open(final_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"📢 *Instagram Post Idee:*\n\n{ai_text}",
                parse_mode="Markdown"
            )

        await update.message.reply_text(
            "🕒 Wanneer wil je dat deze post op Instagram geplaatst wordt?\n"
            "Stuur een tijd in dit formaat: `DD-MM-YYYY HH:MM` (bijv. `17-07-2025 14:30`)",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Fout: {str(e)}")
        await update.message.reply_text(f"❌ Er ging iets mis:\n{str(e)}")
        
# Functie om de post op het geplande tijdstip te plaatsen
async def schedule_instagram_post(user_id, post_time):
    image_path = user_context[user_id]["image_path"]
    caption = user_context[user_id]["caption"]

    # Login en maak een client object
    cl = login_to_instagram()

    # Plan de post
    schedule_post(image_path, caption, post_time)


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



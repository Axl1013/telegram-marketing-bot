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
from telegram.ext import CommandHandler
from instagrapi import Client
from instagrapi.exceptions import *
from apscheduler.schedulers.background import BackgroundScheduler
from telegram.ext import ConversationHandler

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

LOGIN_USERNAME, LOGIN_PASSWORD = range(2)
login_data = {}  # tijdelijke opslag tijdens login


# 🧠 Logging
logging.basicConfig(level=logging.INFO)

# 📦 Context opslag
user_context = {}
scheduler = BackgroundScheduler()
scheduler.start()

BASE_PATH = "data"  # 🗂️ Alle gebruikersdata hier
os.makedirs(BASE_PATH, exist_ok=True)

def get_user_path(user_id):
    return os.path.join(BASE_PATH, str(user_id))

def get_session_path(user_id):
    return os.path.join(get_user_path(user_id), "session.json")

def get_logo_path(user_id):
    return os.path.join(get_user_path(user_id), "logo.png")

def get_schedule_file(user_id):
    return os.path.join(get_user_path(user_id), "scheduled_posts.json")

def ensure_user_dirs(user_id):
    os.makedirs(get_user_path(user_id), exist_ok=True)

# 📸 Instagram login en sessiebeheer
def login_and_save_session(user_id, username, password):
    cl = Client()
    cl.login(username, password)
    ensure_user_dirs(user_id)
    cl.dump_settings(get_session_path(user_id))

def get_instagram_client(user_id, username=None, password=None):
    cl = Client()
    session_path = get_session_path(user_id)

    if os.path.exists(session_path):
        cl.load_settings(session_path)
        try:
            cl.get_timeline_feed()  # om te testen of sessie geldig is
        except LoginRequired:
            if username and password:
                cl.login(username, password)
                cl.dump_settings(session_path)
            else:
                raise Exception("Sessie ongeldig en geen inloggegevens opgegeven.")
    else:
        if username and password:
            cl.login(username, password)
            ensure_user_dirs(user_id)
            cl.dump_settings(session_path)
        else:
            raise Exception("Geen sessie gevonden en geen inloggegevens beschikbaar.")
    
    return cl


def post_on_instagram(image_path, caption, user_id):
    try:
        cl = get_instagram_client(user_id)
        cl.photo_upload(image_path, caption)
        print(f"✅ Post geplaatst op Instagram voor gebruiker {user_id}")
    except Exception as e:
        print(f"❌ Fout bij posten voor gebruiker {user_id}: {e}")


def schedule_post(image_path, caption, post_time, user_id):
    scheduled_time = datetime.strptime(post_time, "%d-%m-%Y %H:%M")
    time_diff = (scheduled_time - datetime.now()).total_seconds()
    if time_diff > 0:
        scheduler.add_job(post_on_instagram, 'date', run_date=scheduled_time,
                          args=[image_path, caption, user_id])
        print(f"📅 Post gepland voor {post_time} (user {user_id})")
    else:
        print("⛔ Tijd ligt in het verleden")

def save_scheduled_post(data, user_id):
    file = get_schedule_file(user_id)
    ensure_user_dirs(user_id)
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump([], f)
    with open(file, "r") as f:
        posts = json.load(f)
    posts.append(data)
    with open(file, "w") as f:
        json.dump(posts, f, indent=2)

def resize_and_crop(image, target_size=1080):
    # Haal de originele afmetingen op
    width, height = image.size

    # Bepaal de dimensie van het vierkant (kleinste van de breedte of hoogte)
    new_dim = min(width, height)

    # Bepaal het bijsnijdgebied (center crop)
    left = (width - new_dim) / 2
    top = (height - new_dim) / 2
    right = (width + new_dim) / 2
    bottom = (height + new_dim) / 2

    # Snijd het beeld bij en schaala naar de doelgrootte
    image_cropped = image.crop((left, top, right, bottom))
    image_resized = image_cropped.resize((target_size, target_size), Image.Resampling.LANCZOS)

    return image_resized


# 🤖 Telegram handlers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ensure_user_dirs(user_id)
    logo_path = get_logo_path(user_id)

    # Controleer of er een bijschrift is toegevoegd aan de foto
    if not update.message.caption:
        await update.message.reply_text("⚠️ Stuur een foto met een promotietekst in het bijschrift.")
        return

    # Controleer of het logo is geüpload
    if not os.path.exists(logo_path):
        await update.message.reply_text("⚠️ Je hebt nog geen logo geüpload. Stuur eerst je logo als foto met bijschrift: `logo`")
        return

    promo_text = update.message.caption
    price_keywords = ["korting", "aanbieding", "prijs", "actie", "promo"]

    # Genereer het prompt voor AI afhankelijk van de aanwezigheid van promotionele woorden
    prompt = (
        f"Schrijf een aantrekkelijke Instagram-post in het Nederlands op basis van deze promotie: '{promo_text}'. "
        f"Voeg relevante hashtags toe en maak het promotioneel, inclusief een prijs of korting."
        if any(keyword in promo_text.lower() for keyword in price_keywords)
        else f"Schrijf een aantrekkelijke Instagram-post in het Nederlands op basis van deze promotie: '{promo_text}'. "
             f"Voeg relevante hashtags toe, zonder een prijs of promotie toe te voegen."
    )

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

        # Verklein en bijsnijd de afbeelding naar een vierkant van 1080x1080px
        final_image = resize_and_crop(original, target_size=1080)

        # Voeg logo toe na het bijsnijden
        logo = Image.open(logo_path).convert("RGBA")
        logo = logo.resize((final_image.width // 2, int(final_image.height // 10)))

        # Positioneer het logo op de afbeelding
        position = (
            final_image.width - logo.width - 20,
            final_image.height - logo.height - 250
        )
        final_image.paste(logo, position, logo)

        # Afbeelding opslaan
        final_path = "final_image.png"
        final_image.save(final_path)

        # Stuur de bewerkte afbeelding terug naar de gebruiker met AI gegenereerde caption
        with open(final_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"📢 *Instagram Post Idee:*\n\n{ai_text}",
                parse_mode="Markdown"
            )

        # Sla de gegevens op in de context om later te plannen
        user_context[user_id] = {
            "image_path": final_path,
            "caption": ai_text,
            "chat_id": update.effective_chat.id
        }

        # Vraag de gebruiker om een tijdstip in te voeren voor het posten op Instagram
        await update.message.reply_text(
            "🕒 Wanneer wil je dat deze post op Instagram geplaatst wordt?\n"
            "Stuur een tijd in dit formaat: `DD-MM-YYYY HH:MM` (bijv. `17-07-2025 14:30`)",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Fout: {str(e)}")
        await update.message.reply_text(f"❌ Er ging iets mis:\n{str(e)}")

async def start_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📲 Wat is je Instagram gebruikersnaam?")
    return LOGIN_USERNAME

async def received_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    login_data[user_id] = {"username": update.message.text}
    await update.message.reply_text("🔐 Wat is je Instagram wachtwoord?")
    return LOGIN_PASSWORD

async def received_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    login_data[user_id]["password"] = update.message.text

    username = login_data[user_id]["username"]
    password = login_data[user_id]["password"]

    try:
        cl = Client()
        cl.login(username, password)

        ensure_user_dirs(user_id)
        cl.dump_settings(get_session_path(user_id))

        await update.message.reply_text("✅ Je bent succesvol ingelogd op Instagram!")
        del login_data[user_id]
        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_text(f"❌ Login mislukt: {str(e)}")
        del login_data[user_id]
        return ConversationHandler.END

async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔ Login geannuleerd.")
    return ConversationHandler.END

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

        save_scheduled_post(post_data, user_id)
        schedule_post(post_data["image_path"], post_data["caption"], post_data["post_time"], user_id)
        del user_context[user_id]

        await update.message.reply_text(f"✅ Post gepland voor {post_time.strftime('%d-%m-%Y %H:%M')}!")

    except ValueError:
        await update.message.reply_text("❌ Ongeldig formaat. Gebruik `DD-MM-YYYY HH:MM`.")

async def handle_logo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.caption and update.message.caption.strip().lower() == "logo":
        user_id = update.effective_user.id
        photo = update.message.photo[-1]
        file = await photo.get_file()
        file_bytes = await file.download_as_bytearray()

        ensure_user_dirs(user_id)
        logo_path = get_logo_path(user_id)
        with open(logo_path, "wb") as f:
            f.write(file_bytes)

        await update.message.reply_text("✅ Je logo is opgeslagen en zal voortaan worden toegevoegd aan je posts.")
    else:
        await handle_message(update, context)

async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        if len(context.args) != 2:
            await update.message.reply_text("⚠️ Gebruik: `/login gebruikersnaam wachtwoord`", parse_mode="Markdown")
            return

        username, password = context.args
        cl = Client()

        await update.message.reply_text("🔐 Aan het inloggen...")

        cl.login(username, password)

        # Zorg voor directories en sla sessie op
        ensure_user_dirs(user_id)
        cl.dump_settings(get_session_path(user_id))

        await update.message.reply_text("✅ Login geslaagd en sessie opgeslagen!")
    except LoginRequired:
        await update.message.reply_text("❌ Login vereist. Controleer je gegevens.")
    except ChallengeRequired:
        await update.message.reply_text("⚠️ Extra verificatie vereist (2FA of e-mail bevestiging).")
    except Exception as e:
        await update.message.reply_text(f"❌ Fout bij inloggen: {str(e)}")

        
def get_session_path(user_id):
    return f"sessions/session_{user_id}.json"

def get_logo_path(user_id):
    return f"logos/logo_{user_id}.png"

def get_schedule_file(user_id):
    return f"scheduled_posts_{user_id}.json"

def ensure_user_dirs(user_id):
    os.makedirs("sessions", exist_ok=True)
    os.makedirs("logos", exist_ok=True)

# 🚀 Start
async def main():
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_logo_upload))
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_schedule_time))
    bot_app.add_handler(CommandHandler("login", handle_login))
    logging.info("✅ Bot gestart...")
    await bot_app.run_polling()
    login_handler = ConversationHandler(
    entry_points=[CommandHandler("login", start_login)],
    states={
        LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_username)],
        LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_password)],
    },
    fallbacks=[CommandHandler("cancel", cancel_login)],
)

    bot_app.add_handler(login_handler)


if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())

import datetime
import time
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from dateutil import parser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

# Functie om de gebruiker om een datum en tijd te vragen
async def ask_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Vraag de gebruiker naar een datum en tijd voor de geplande post
    await update.message.reply_text("📅 Geef een datum en tijd waarop je dit wilt posten (bijv. 15-07-2025 14:30):")
    # Sla de status van de gebruiker op zodat we de datum kunnen krijgen
    context.user_data['waiting_for_datetime'] = True

# Functie om de datum en tijd van de gebruiker te verwerken
async def process_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'waiting_for_datetime' not in context.user_data:
        return
    
    # Haal de invoer van de gebruiker op
    user_input = update.message.text.strip()
    
    try:
        # Probeer de invoer om te zetten naar een datetime object
        scheduled_time = parser.parse(user_input)

        # Controleer of de opgegeven tijd in de toekomst ligt
        if scheduled_time < datetime.datetime.now():
            await update.message.reply_text("❌ De ingevoerde tijd is in het verleden. Kies een tijd in de toekomst.")
            return

        # Sla de geplande tijd op en bevestig
        context.user_data['scheduled_time'] = scheduled_time
        await update.message.reply_text(f"✅ De post is gepland voor {scheduled_time.strftime('%d-%m-%Y %H:%M')}.")

        # Roep de functie aan om de post in te plannen
        schedule_post(scheduled_time, update, context)

    except ValueError:
        await update.message.reply_text("❌ Ongeldig formaat. Gebruik het formaat: 'dd-mm-jjjj uu:mm'.")
        return

    # Verwijder de status na verwerking
    del context.user_data['waiting_for_datetime']

# Functie om de post te plannen met behulp van een scheduler
def schedule_post(scheduled_time: datetime.datetime, update: Update, context: ContextTypes.DEFAULT_TYPE):
    scheduler = AsyncIOScheduler()

    # Plan de taak om de post op het juiste moment te plaatsen
    scheduler.add_job(lambda: post_on_instagram(update, context), 'date', run_date=scheduled_time)
    
    scheduler.start()

# Functie om de post op Instagram te plaatsen (simulatie)
async def post_on_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Dit is de simulatie van de post (je moet hier de code voor echte plaatsing invoegen)
    promo_text = "🎉 Hier is je Instagram post!"
    # Gebruik bijvoorbeeld een placeholder-tekst voor de post
    await update.message.reply_text(f"📢 De post wordt nu geplaatst op Instagram:\n\n{promo_text}")

# Functie om de berichtverwerking aan te passen
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.caption:
        await update.message.reply_text("⚠️ Stuur een foto met een promotietekst in het bijschrift.")
        return

    promo_text = update.message.caption.strip()
    # Controleren of de tekst een prijs of promotie bevat (bijvoorbeeld door het zoeken naar woorden zoals "korting", "aanbieding", "prijs", etc.)
    price_keywords = ["korting", "aanbieding", "prijs", "actie", "promo"]
    if any(keyword in promo_text.lower() for keyword in price_keywords):
        prompt = f"Schrijf een aantrekkelijke Instagram-post op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe en maak het promotioneel, inclusief een prijs of korting."
    else:
        prompt = f"Schrijf een aantrekkelijke Instagram-post op basis van deze promotie: '{promo_text}'. Voeg relevante hashtags toe, zonder een prijs of promotie toe te voegen."

    

    try:
        # AI-caption genereren
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        ai_text = response.choices[0].message.content.strip()

        # Vraag de gebruiker om een datum en tijd
        await ask_datetime(update, context)

        # Hier kun je de foto verwerken zoals je dat eerder hebt gedaan...

    except Exception as e:
        logging.error(f"Fout: {str(e)}")
        await update.message.reply_text(f"❌ Er ging iets mis:\n{str(e)}")

async def main():
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.PHOTO & filters.Caption(), handle_message))
    bot_app.add_handler(MessageHandler(filters.TEXT, process_datetime))  # Handler voor het invoeren van de datum en tijd
    logging.info("✅ Bot gestart...")
    await bot_app.run_polling()
if __name__ == "__main__":
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())


import os
import logging
import asyncio
from datetime import time, datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, JobQueue, 
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from dotenv import load_dotenv

# Import our modules
import database
import price_service

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")

# States for ConversationHandler
SELECT_TIMEZONE, SELECT_TIME = range(2)

# Common timezones map
TIMEZONES = {
    "Nicosia (UTC+3)": "Asia/Nicosia",
    "London (UTC+0)": "Europe/London",
    "Central Europe (UTC+1)": "Europe/Paris",
    "Moscow (UTC+3)": "Europe/Moscow",
    "Dubai (UTC+4)": "Asia/Dubai",
    "New York (UTC-5)": "America/New_York",
    "Los Angeles (UTC-8)": "America/Los_Angeles",
    "Tokyo (UTC+9)": "Asia/Tokyo",
    "UTC": "UTC"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the /start command.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Get current UTC time
    current_utc_time = datetime.now(pytz.utc).time()
    
    # Add subscription to database
    database.add_subscription(user_id, chat_id, current_utc_time, 'UTC')
    
    # Schedule the daily job
    context.job_queue.run_daily(
        send_daily_notification_job,
        time=current_utc_time,
        chat_id=chat_id,
        name=str(user_id),
        data=user_id
    )
    
    time_str = current_utc_time.strftime('%H:%M')

    await update.message.reply_text(
        "👋 **Welcome to the Market Notifier Bot!**\n\n"
        "I can send you daily updates on Crypto, Metals, Oil, and Currencies.\n\n"
        f"✅ **Auto-Subscription Added!**\n"
        f"You have been automatically subscribed to receive daily updates at this exact time ({time_str} UTC).\n\n"
        "Use /subscriptions to manage your notifications.\n"
        "Use /price to get current prices immediately."
    )
    # Send immediate update
    await send_price_update(chat_id, context)

async def send_price_update(chat_id, context):
    """Helper to send price update."""
    message = price_service.get_prices()
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /price command."""
    await update.message.reply_text("Fetching prices... ⏳")
    await send_price_update(update.effective_chat.id, context)

async def subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /subscriptions command."""
    user_id = update.effective_user.id
    subs = database.get_user_subscriptions(user_id)
    
    text = "📋 **Your Subscriptions:**\n\n"
    if not subs:
        text += "You have no active subscriptions."
    else:
        for i, sub in enumerate(subs, 1):
            t = sub['notification_time'].strftime('%H:%M')
            tz = sub['timezone']
            text += f"{i}. {t} ({tz})\n"
            
    keyboard = [[InlineKeyboardButton("➕ Add Subscription", callback_data='add_sub')]]
    if subs:
        keyboard.append([InlineKeyboardButton("❌ Remove All", callback_data='remove_all')])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def add_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the add subscription flow."""
    query = update.callback_query
    await query.answer()
    
    keyboard = []
    row = []
    for label, tz in TIMEZONES.items():
        row.append(InlineKeyboardButton(label, callback_data=f"tz_{tz}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🌍 **Select your Timezone:**\n"
        "Choose the city closest to you or your preferred time zone.",
        reply_markup=reply_markup
    )
    return SELECT_TIMEZONE

async def timezone_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for timezone selection."""
    query = update.callback_query
    await query.answer()
    
    tz_name = query.data.replace("tz_", "")
    context.user_data['timezone'] = tz_name
    
    await query.edit_message_text(
        f"✅ Timezone selected: {tz_name}\n\n"
        "⏰ **At what time do you want to receive notifications?**\n"
        "Please reply with the time in **HH:MM** format (24-hour).\n"
        "Example: `09:00` or `14:30`"
    )
    return SELECT_TIME

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for time input."""
    time_str = update.message.text.strip()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    tz_name = context.user_data.get('timezone', 'UTC')
    
    try:
        # Parse time
        h, m = map(int, time_str.split(':'))
        user_time = time(hour=h, minute=m)
        
        # Convert to UTC for storage/scheduling
        local_dt = datetime.now(pytz.timezone(tz_name)).replace(hour=h, minute=m, second=0, microsecond=0)
        utc_dt = local_dt.astimezone(pytz.utc)
        utc_time = utc_dt.time()
        
        # Save to DB
        database.add_subscription(user_id, chat_id, utc_time, tz_name)
        
        # Schedule job
        context.job_queue.run_daily(
            send_daily_notification_job,
            time=utc_time,
            chat_id=chat_id,
            name=str(user_id), # Note: this name is not unique if multiple subs, but fine for now
            data=user_id
        )
        
        await update.message.reply_text(
            f"✅ **Subscription Added!**\n"
            f"You will receive updates daily at **{time_str}** ({tz_name})."
        )
        
        # Send immediate update as requested
        await send_price_update(chat_id, context)
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("⚠️ Invalid format. Please use **HH:MM** (e.g., 14:30). Try again:")
        return SELECT_TIME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the conversation."""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def remove_all_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes all subscriptions for the user."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    database.remove_subscription(user_id)
    
    # Remove jobs
    # Note: This removes ALL jobs for this user.
    # If we had unique job names per sub, we could be more specific.
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()
        
    await query.edit_message_text("🗑️ All subscriptions removed.")

async def send_daily_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """The job function that sends the price update."""
    job = context.job
    chat_id = job.chat_id
    message = price_service.get_prices()
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

async def restore_jobs(context: ContextTypes.DEFAULT_TYPE):
    """Restores scheduled jobs from the database on bot startup."""
    subscriptions = database.get_all_subscriptions()
    count = 0
    
    for sub in subscriptions:
        user_id = sub['user_id']
        chat_id = sub['chat_id']
        notification_time = sub['notification_time'] # This is UTC time from DB
        
        context.job_queue.run_daily(
            send_daily_notification_job,
            time=notification_time,
            chat_id=chat_id,
            name=str(user_id),
            data=user_id
        )
        count += 1
        
    logger.info(f"Restored {count} subscriptions from database.")

async def update_price_cache_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job to update price cache periodically."""
    price_service.update_cache()

if __name__ == '__main__':
    # Initialize Database
    database.init_db()
    
    if not TOKEN:
        logger.error("Error: TELEGRAM_TOKEN not found in .env file.")
        exit(1)

    # Build Application
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Conversation Handler for Adding Subscription
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_sub_start, pattern='^add_sub$')],
        states={
            SELECT_TIMEZONE: [CallbackQueryHandler(timezone_selected, pattern='^tz_')],
            SELECT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('price', price_command))
    application.add_handler(CommandHandler('subscriptions', subscriptions_command))
    application.add_handler(CallbackQueryHandler(remove_all_subs, pattern='^remove_all$'))
    application.add_handler(conv_handler)
    
    # Restore jobs on startup
    application.job_queue.run_once(restore_jobs, when=0)
    
    # Schedule background cache update every 15 minutes
    application.job_queue.run_repeating(update_price_cache_job, interval=900, first=1)

    logger.info("Bot is starting...")
    
    # Run the bot
    application.run_polling()
import os
import logging
import asyncio
from datetime import time, datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, JobQueue
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the /start command.
    Schedules a daily notification at the current time.
    """
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Get current time (UTC)
    # We use UTC because servers usually run on UTC.
    # The user will receive the notification at the same time they clicked /start.
    now = datetime.utcnow()
    notification_time = now.time()
    
    # Save to database
    database.add_subscription(user_id, chat_id, notification_time)
    
    # Schedule the job
    # Remove existing job if any to avoid duplicates
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()
        
    # Schedule new job
    context.job_queue.run_daily(
        send_daily_notification,
        time=notification_time,
        chat_id=chat_id,
        name=str(user_id),
        data=user_id
    )
    
    await update.message.reply_text(
        f"✅ **Subscription Active!**\n\n"
        f"You will receive a market update every day at this time ({notification_time.strftime('%H:%M')} UTC).\n"
        f"Sit back and relax! 🚀"
    )

    # Send immediate update
    await update.message.reply_text("Fetching current prices for you... ⏳")
    message = price_service.get_prices()
    await update.message.reply_text(message, parse_mode='Markdown')

async def send_daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """
    The job function that sends the price update.
    """
    job = context.job
    chat_id = job.chat_id
    
    # Fetch prices
    message = price_service.get_prices()
    
    # Send message
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

async def restore_jobs(context: ContextTypes.DEFAULT_TYPE):
    """
    Restores scheduled jobs from the database on bot startup.
    """
    subscriptions = database.get_all_subscriptions()
    count = 0
    
    for sub in subscriptions:
        user_id = sub['user_id']
        chat_id = sub['chat_id']
        notification_time = sub['notification_time'] # This is a datetime.time object
        
        # Schedule the job
        context.job_queue.run_daily(
            send_daily_notification,
            time=notification_time,
            chat_id=chat_id,
            name=str(user_id),
            data=user_id
        )
        count += 1
        
    logger.info(f"Restored {count} subscriptions from database.")

async def update_price_cache_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Background job to update price cache periodically.
    """
    price_service.update_cache()

if __name__ == '__main__':
    # Initialize Database
    database.init_db()
    
    if not TOKEN:
        logger.error("Error: TELEGRAM_TOKEN not found in .env file.")
        exit(1)

    # Build Application
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Add Handlers
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)
    
    # Restore jobs on startup
    # We schedule a job to run immediately (when=0) to restore subscriptions
    application.job_queue.run_once(restore_jobs, when=0)
    
    # Schedule background cache update every 15 minutes (900s)
    # Run immediately on startup (first=1)
    application.job_queue.run_repeating(update_price_cache_job, interval=900, first=1)

    logger.info("Bot is starting...")
    
    # Run the bot
    application.run_polling()
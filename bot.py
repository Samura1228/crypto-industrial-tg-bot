import os
import logging
import asyncio
from datetime import time, datetime, timedelta
import pytz
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, JobQueue,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler,
    ChatMemberHandler
)
from dotenv import load_dotenv

# Import our modules
import database
import price_service
from price_service import ASSET_REGISTRY, ALL_ASSET_KEYS

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")

# States for ConversationHandler (legacy add-subscription flow)
SELECT_TIMEZONE, SELECT_TIME = range(2)

# States for new /start conversation flow
START_ASSET_SELECTION, START_SELECT_TIMEZONE, START_SELECT_TIME = range(10, 13)

# States for /settings conversation flow
SETTINGS_ASSET_SELECTION = 20

# States for /groupprice conversation flow
GP_ASSET_SELECTION = 30
GP_WAITING_FOR_GROUP = 31

# Test user IDs that get the new flow
NEW_FLOW_USER_IDS = {6840070959}

def is_new_flow_user(user_id: int) -> bool:
    """Gate function: returns True if user should see the new asset selection flow."""
    return user_id in NEW_FLOW_USER_IDS

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

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def build_timezone_keyboard():
    """Builds the timezone selection inline keyboard."""
    keyboard = []
    row = []
    for label, tz in TIMEZONES.items():
        row.append(InlineKeyboardButton(label, callback_data=f"tz_{tz}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

def build_asset_keyboard(selected: set) -> list:
    """Builds inline keyboard with toggle indicators for asset selection."""
    keyboard = []
    row = []
    for asset in ASSET_REGISTRY:
        check = "✅" if asset["key"] in selected else "☐"
        btn = InlineKeyboardButton(
            f"{check} {asset['emoji']} {asset['label']}",
            callback_data=f"asset_toggle_{asset['key']}"
        )
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Select All / Deselect All
    all_selected = len(selected) == len(ASSET_REGISTRY)
    toggle_text = "☐ Deselect All" if all_selected else "✅ Select All"
    keyboard.append([InlineKeyboardButton(toggle_text, callback_data="asset_toggle_all")])

    # Confirm button (only if at least 1 selected)
    if selected:
        keyboard.append([InlineKeyboardButton("✅ Confirm Selection", callback_data="asset_confirm")])

    return keyboard

async def send_price_update(chat_id, context):
    """Helper to send price update with all assets."""
    message = price_service.get_prices()
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

# ---------------------------------------------------------------------------
# /start command — branches between new and legacy flow
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command. Branches based on user ID."""
    user_id = update.effective_user.id

    if is_new_flow_user(user_id):
        return await start_new_flow(update, context)
    else:
        return await start_legacy_flow(update, context)

async def start_legacy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy /start flow: auto-subscribe at current UTC time, send all prices."""
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
    return ConversationHandler.END

async def start_new_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """New /start flow: welcome → all prices → asset selection keyboard."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Send welcome
    await update.message.reply_text(
        "👋 **Welcome to the Market Notifier Bot!**\n\n"
        "Here are the current market prices:",
        parse_mode='Markdown'
    )

    # Send ALL prices (one-time, informational)
    await send_price_update(chat_id, context)

    # Initialize selection state — pre-populate with existing preferences or all selected
    existing = database.get_user_assets(user_id)
    if existing is not None:
        context.user_data['selected_assets'] = set(existing)
    else:
        context.user_data['selected_assets'] = set(ALL_ASSET_KEYS)

    # Show asset selection keyboard
    keyboard = build_asset_keyboard(context.user_data['selected_assets'])
    await update.message.reply_text(
        "📌 **Choose which assets you want in your daily update:**\n"
        "Tap to toggle on/off, then press Confirm.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return START_ASSET_SELECTION

# ---------------------------------------------------------------------------
# Asset toggle / confirm handlers (shared by /start new flow and /settings)
# ---------------------------------------------------------------------------

async def asset_toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles toggling individual assets or select/deselect all."""
    query = update.callback_query
    await query.answer()

    selected = context.user_data.get('selected_assets', set())
    data = query.data

    if data == "asset_toggle_all":
        if len(selected) == len(ASSET_REGISTRY):
            selected.clear()
        else:
            selected = set(ALL_ASSET_KEYS)
    else:
        key = data.replace("asset_toggle_", "")
        if key in selected:
            selected.discard(key)
        else:
            selected.add(key)

    context.user_data['selected_assets'] = selected
    keyboard = build_asset_keyboard(selected)
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    # Return the appropriate state depending on which flow we're in
    return context.user_data.get('_asset_selection_state', START_ASSET_SELECTION)

async def asset_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles confirm button press — saves assets, proceeds to timezone selection."""
    query = update.callback_query

    selected = context.user_data.get('selected_assets', set())
    if not selected:
        await query.answer("Please select at least one asset!", show_alert=True)
        return context.user_data.get('_asset_selection_state', START_ASSET_SELECTION)

    await query.answer()

    # Save assets to DB
    user_id = query.from_user.id
    database.save_user_assets(user_id, list(selected))

    # Check which flow we're in
    flow = context.user_data.get('_asset_flow', 'start')

    if flow == 'settings':
        # Settings flow: just confirm and end
        asset_names = []
        for asset in ASSET_REGISTRY:
            if asset["key"] in selected:
                asset_names.append(f"{asset['emoji']} {asset['label']}")
        asset_list = "\n".join(asset_names)

        await query.edit_message_text(
            f"✅ **Preferences updated! ({len(selected)} assets selected)**\n\n"
            f"{asset_list}\n\n"
            "Your next daily notification will use these settings.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    if flow == 'groupprice':
        # Group price board flow: save pending board, show instructions
        board_id = database.create_group_price_board(user_id, list(selected))
        context.user_data['_gp_board_id'] = board_id

        # Build asset summary
        asset_names = []
        for asset in ASSET_REGISTRY:
            if asset["key"] in selected:
                asset_names.append(f"{asset['emoji']} {asset['label']}")
        asset_list = "\n".join(asset_names)

        await query.edit_message_text(
            f"✅ **{len(selected)} assets selected for group board:**\n\n"
            f"{asset_list}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📋 **Now follow these steps:**\n\n"
            "1️⃣ **Create a group** (or open an existing one)\n\n"
            "2️⃣ **Add me to the group:**\n"
            "   Search for `@notifiercrypto_ind_bot` and add me\n\n"
            "3️⃣ **Make me an admin** with these permissions:\n"
            "   • ✅ Send messages\n"
            "   • ✅ Pin messages\n\n"
            "⏳ I'm waiting for you to add me to a group...\n"
            "Once you do, I'll automatically send and pin the price board!",
            parse_mode='Markdown'
        )
        return GP_WAITING_FOR_GROUP

    # Start flow: proceed to timezone selection
    keyboard = build_timezone_keyboard()
    await query.edit_message_text(
        f"✅ **{len(selected)} assets selected!**\n\n"
        "🌍 **Now choose your timezone:**\n"
        "Choose the city closest to you or your preferred time zone.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return START_SELECT_TIMEZONE

# ---------------------------------------------------------------------------
# New /start flow — timezone and time handlers
# ---------------------------------------------------------------------------

async def start_timezone_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Timezone selection in the new /start flow."""
    query = update.callback_query
    await query.answer()

    tz_name = query.data.replace("tz_", "")
    context.user_data['timezone'] = tz_name

    await query.edit_message_text(
        f"✅ Timezone selected: **{tz_name}**\n\n"
        "⏰ **At what time do you want to receive notifications?**\n"
        "Please reply with the time in **HH:MM** format (24-hour).\n"
        "Example: `09:00` or `14:30`",
        parse_mode='Markdown'
    )
    return START_SELECT_TIME

async def start_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Time input in the new /start flow."""
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

        # Save subscription to DB
        database.add_subscription(user_id, chat_id, utc_time, tz_name)

        # Schedule daily job
        context.job_queue.run_daily(
            send_daily_notification_job,
            time=utc_time,
            chat_id=chat_id,
            name=str(user_id),
            data=user_id
        )

        # Build confirmation message with selected assets
        selected = context.user_data.get('selected_assets', set())
        asset_names = []
        for asset in ASSET_REGISTRY:
            if asset["key"] in selected:
                asset_names.append(f"{asset['emoji']} {asset['label']}")
        asset_list = "\n".join(asset_names)

        await update.message.reply_text(
            f"✅ **Subscription Added!**\n\n"
            f"📊 **Your selected assets ({len(selected)}):**\n"
            f"{asset_list}\n\n"
            f"⏰ **Daily updates at:** {time_str} ({tz_name})\n\n"
            "Use /settings to change your asset selection.\n"
            "Use /subscriptions to manage notification times.\n"
            "Use /price to get current prices immediately.",
            parse_mode='Markdown'
        )

        # Send immediate filtered update
        message = price_service.get_filtered_prices(list(selected))
        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid format. Please use **HH:MM** (e.g., 14:30). Try again:",
            parse_mode='Markdown'
        )
        return START_SELECT_TIME

# ---------------------------------------------------------------------------
# /settings command — re-open asset selection for new-flow users
# ---------------------------------------------------------------------------

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /settings — allows new-flow users to change asset preferences."""
    user_id = update.effective_user.id

    if not is_new_flow_user(user_id):
        await update.message.reply_text(
            "This command is not available yet. Use /subscriptions to manage your notifications."
        )
        return ConversationHandler.END

    # Load existing preferences or default to all
    existing = database.get_user_assets(user_id)
    if existing is not None:
        context.user_data['selected_assets'] = set(existing)
    else:
        context.user_data['selected_assets'] = set(ALL_ASSET_KEYS)

    # Mark this as settings flow so confirm handler knows what to do
    context.user_data['_asset_flow'] = 'settings'
    context.user_data['_asset_selection_state'] = SETTINGS_ASSET_SELECTION

    keyboard = build_asset_keyboard(context.user_data['selected_assets'])
    await update.message.reply_text(
        "⚙️ **Settings — Asset Selection**\n\n"
        "Tap to toggle assets on/off, then press Confirm to save.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SETTINGS_ASSET_SELECTION

# ---------------------------------------------------------------------------
# Legacy subscription management (unchanged)
# ---------------------------------------------------------------------------

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /price command."""
    await update.message.reply_text("Fetching prices... ⏳")
    await send_price_update(update.effective_chat.id, context)

async def subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /subscriptions command."""
    user_id = update.effective_user.id

    if is_new_flow_user(user_id):
        await _subscriptions_new_flow(update, context)
    else:
        await _subscriptions_legacy_flow(update, context)


async def _subscriptions_legacy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy /subscriptions display (unchanged behaviour)."""
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


def _build_subscriptions_text_and_keyboard(subs_with_ids: list):
    """Build the subscription list text and inline keyboard for new-flow users.

    Parameters
    ----------
    subs_with_ids : list[dict]
        Each dict has keys 'id', 'notification_time', 'timezone'.

    Returns
    -------
    tuple[str, InlineKeyboardMarkup]
    """
    text = "📋 **Your Subscriptions:**\n\n"
    keyboard = []

    if not subs_with_ids:
        text += "You have no active subscriptions."
    else:
        for i, sub in enumerate(subs_with_ids, 1):
            t = sub['notification_time'].strftime('%H:%M')
            tz = sub['timezone']
            text += f"{i}. {t} ({tz})\n"

        # One remove button per subscription
        for i, sub in enumerate(subs_with_ids, 1):
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 Remove #{i}",
                    callback_data=f"remove_sub:{sub['id']}"
                )
            ])

        # Remove All button
        keyboard.append([InlineKeyboardButton("🗑 Remove All", callback_data='remove_all')])

    # Add Subscription button (always shown)
    keyboard.append([InlineKeyboardButton("➕ Add Subscription", callback_data='add_sub')])

    return text, InlineKeyboardMarkup(keyboard)


async def _subscriptions_new_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """New-flow /subscriptions display with per-subscription remove buttons."""
    user_id = update.effective_user.id
    subs = database.get_user_subscriptions_with_ids(user_id)
    text, reply_markup = _build_subscriptions_text_and_keyboard(subs)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def remove_single_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler: remove a single subscription by its DB id."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Parse subscription id from callback data  (format: "remove_sub:<id>")
    try:
        sub_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("Invalid subscription reference.", show_alert=True)
        return

    # Determine the display index *before* deletion so we can show a nice message
    subs_before = database.get_user_subscriptions_with_ids(user_id)
    display_index = None
    for i, s in enumerate(subs_before, 1):
        if s['id'] == sub_id:
            display_index = i
            break

    if display_index is None:
        await query.answer("Subscription not found — it may have been removed already.", show_alert=True)
        return

    # Remove from database
    database.remove_subscription_by_id(sub_id)

    # Cancel ALL scheduled jobs for this user, then re-schedule remaining ones
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()

    remaining_subs = database.get_user_subscriptions_with_ids(user_id)
    chat_id = query.message.chat_id
    for sub in remaining_subs:
        context.job_queue.run_daily(
            send_daily_notification_job,
            time=sub['notification_time'],
            chat_id=chat_id,
            name=str(user_id),
            data=user_id
        )

    # Refresh the message with updated list and buttons
    text, reply_markup = _build_subscriptions_text_and_keyboard(remaining_subs)
    text += f"\n\n✅ Subscription #{display_index} removed."
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the add subscription flow."""
    query = update.callback_query
    await query.answer()

    keyboard = build_timezone_keyboard()
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🌍 **Select your Timezone:**\n"
        "Choose the city closest to you or your preferred time zone.",
        reply_markup=reply_markup
    )
    return SELECT_TIMEZONE

async def timezone_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for timezone selection (legacy add-sub flow)."""
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
    """Handler for time input (legacy add-sub flow)."""
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
            name=str(user_id),
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

# ---------------------------------------------------------------------------
# /groupprice command and related handlers
# ---------------------------------------------------------------------------

async def groupprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /groupprice — sets up a live price board in a group."""
    user_id = update.effective_user.id

    # Gate check
    if not is_new_flow_user(user_id):
        await update.message.reply_text("This command is not available yet.")
        return ConversationHandler.END

    # Only works in private chat
    if update.effective_chat.type != 'private':
        await update.message.reply_text(
            "⚠️ Please use /groupprice in a private chat with me, not in a group."
        )
        return ConversationHandler.END

    # Explain the feature
    await update.message.reply_text(
        "📌 **Group Price Board**\n\n"
        "This feature lets you set up a **live-updating pinned message** "
        "in a Telegram group that shows current market prices.\n\n"
        "**How it works:**\n"
        "1️⃣ You choose which assets to display\n"
        "2️⃣ You add me to a group and make me admin\n"
        "3️⃣ I'll send and pin a price message\n"
        "4️⃣ I'll update it every hour automatically\n\n"
        "Let's start by choosing your assets! 👇",
        parse_mode='Markdown'
    )

    # Cancel any existing pending boards for this user
    database.cancel_pending_boards(user_id)

    # Initialize asset selection — pre-populate with existing preferences or all
    existing = database.get_user_assets(user_id)
    if existing is not None:
        context.user_data['selected_assets'] = set(existing)
    else:
        context.user_data['selected_assets'] = set(ALL_ASSET_KEYS)

    # Mark flow context for shared handlers
    context.user_data['_asset_flow'] = 'groupprice'
    context.user_data['_asset_selection_state'] = GP_ASSET_SELECTION

    # Show asset selection keyboard (reuse existing)
    keyboard = build_asset_keyboard(context.user_data['selected_assets'])
    await update.message.reply_text(
        "📊 **Select assets for the group price board:**\n"
        "Tap to toggle on/off, then press Confirm.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return GP_ASSET_SELECTION


async def gp_waiting_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remind user we're waiting for them to add the bot to a group."""
    await update.message.reply_text(
        "⏳ I'm still waiting for you to add me to a group.\n\n"
        "Follow the steps above, and I'll automatically detect when you add me!\n\n"
        "Use /cancel to abort.",
        parse_mode='Markdown'
    )
    return GP_WAITING_FOR_GROUP


async def gp_timeout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle conversation timeout for groupprice flow."""
    if update.effective_user:
        user_id = update.effective_user.id
        database.cancel_pending_boards(user_id)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ChatMemberUpdated handler — detect bot added to group
# ---------------------------------------------------------------------------

def format_group_price_message(asset_keys: list) -> str:
    """Format the price message for a group price board."""
    message = price_service.get_filtered_prices(asset_keys)

    # Add a footer with the last update time
    now = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M UTC')
    message += f"🔄 _Last updated: {now}_"

    return message


async def bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the bot being added to a group chat."""
    my_member = update.my_chat_member
    if my_member is None:
        return

    old_status = my_member.old_chat_member.status
    new_status = my_member.new_chat_member.status

    # We only care about transitions TO member or administrator
    if new_status not in ('member', 'administrator'):
        return

    # Ignore if old status was already member/admin (e.g., permissions change)
    if old_status in ('member', 'administrator'):
        # But DO handle member -> administrator (might now have pin permissions)
        if not (old_status == 'member' and new_status == 'administrator'):
            return

    group_chat_id = my_member.chat.id
    adder_user_id = my_member.from_user.id

    logger.info(
        f"Bot added to group {group_chat_id} by user {adder_user_id} "
        f"(status: {old_status} -> {new_status})"
    )

    # Check if this user has a pending group price board
    pending = database.get_pending_board_for_user(adder_user_id)

    if pending is None:
        logger.info(f"No pending board for user {adder_user_id}, ignoring.")
        return

    # Parse asset keys from the pending board
    asset_keys = pending['asset_keys'].split(',')

    try:
        # Generate the price message
        price_message = format_group_price_message(asset_keys)

        # Send the message to the group
        sent_message = await context.bot.send_message(
            chat_id=group_chat_id,
            text=price_message,
            parse_mode='Markdown'
        )

        # Try to pin the message
        pinned = False
        try:
            await context.bot.pin_chat_message(
                chat_id=group_chat_id,
                message_id=sent_message.message_id,
                disable_notification=True
            )
            pinned = True
        except Exception as pin_error:
            logger.warning(f"Could not pin message in group {group_chat_id}: {pin_error}")

        # Activate the board in the database
        database.activate_group_price_board(
            board_id=pending['id'],
            group_chat_id=group_chat_id,
            pinned_message_id=sent_message.message_id
        )

        # Schedule the hourly update job
        context.job_queue.run_repeating(
            update_group_price_board_job,
            interval=3600,
            first=3600,
            chat_id=group_chat_id,
            name=f"gp_{pending['id']}",
            data={
                'board_id': pending['id'],
                'group_chat_id': group_chat_id,
                'message_id': sent_message.message_id,
                'asset_keys': asset_keys,
            }
        )

        # Notify the user in private chat
        pin_status = "📌 Message pinned!" if pinned else "⚠️ Could not pin the message — please make me an admin with pin permissions."
        try:
            await context.bot.send_message(
                chat_id=adder_user_id,
                text=(
                    f"✅ **Group Price Board is live!**\n\n"
                    f"Group: {my_member.chat.title or 'Unknown'}\n"
                    f"{pin_status}\n\n"
                    f"The prices will update automatically every hour."
                ),
                parse_mode='Markdown'
            )
        except Exception as notify_error:
            logger.warning(f"Could not notify user {adder_user_id}: {notify_error}")

    except Exception as e:
        logger.error(f"Error setting up group price board: {e}")
        try:
            await context.bot.send_message(
                chat_id=adder_user_id,
                text=(
                    f"❌ **Failed to set up the price board.**\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please make sure I have permission to send messages in the group.\n"
                    "Use /groupprice to try again."
                ),
                parse_mode='Markdown'
            )
        except Exception:
            pass


async def update_group_price_board_job(context: ContextTypes.DEFAULT_TYPE):
    """Job that edits the pinned message in a group with fresh prices."""
    job = context.job
    data = job.data
    board_id = data['board_id']
    group_chat_id = data['group_chat_id']
    message_id = data['message_id']
    asset_keys = data['asset_keys']

    try:
        # Generate fresh price message
        new_text = format_group_price_message(asset_keys)

        # Edit the existing pinned message
        await context.bot.edit_message_text(
            chat_id=group_chat_id,
            message_id=message_id,
            text=new_text,
            parse_mode='Markdown'
        )
        logger.info(f"Updated group price board {board_id} in chat {group_chat_id}")

    except telegram.error.BadRequest as e:
        error_msg = str(e).lower()
        if 'message is not modified' in error_msg:
            logger.debug(f"Board {board_id}: message not modified (prices unchanged)")
        elif 'message to edit not found' in error_msg:
            logger.warning(f"Board {board_id}: pinned message deleted, deactivating")
            database.deactivate_board(board_id)
            job.schedule_removal()
        elif 'chat not found' in error_msg or 'bot was kicked' in error_msg:
            logger.warning(f"Board {board_id}: bot removed from group, deactivating")
            database.deactivate_board(board_id)
            job.schedule_removal()
        else:
            logger.error(f"Board {board_id}: BadRequest editing message: {e}")

    except telegram.error.Forbidden as e:
        logger.warning(f"Board {board_id}: Forbidden — {e}, deactivating")
        database.deactivate_board(board_id)
        job.schedule_removal()

    except Exception as e:
        logger.error(f"Board {board_id}: Unexpected error updating price board: {e}")


async def remove_all_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes all subscriptions for the user."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    database.remove_subscription(user_id)

    # Remove jobs
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()

    await query.edit_message_text("🗑️ All subscriptions removed.")

# ---------------------------------------------------------------------------
# Daily notification job — now supports filtered prices
# ---------------------------------------------------------------------------

async def send_daily_notification_job(context: ContextTypes.DEFAULT_TYPE):
    """The job function that sends the price update, filtered by user preferences."""
    job = context.job
    chat_id = job.chat_id
    user_id = job.data

    # Get user's asset preferences
    asset_keys = database.get_user_assets(user_id)

    if asset_keys is not None:
        # User has configured preferences — send filtered prices
        message = price_service.get_filtered_prices(asset_keys)
    else:
        # No preferences (legacy user) — send all prices
        message = price_service.get_prices()

    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

async def restore_jobs(context: ContextTypes.DEFAULT_TYPE):
    """Restores scheduled jobs from the database on bot startup."""
    subscriptions = database.get_all_subscriptions()
    count = 0

    for sub in subscriptions:
        user_id = sub['user_id']
        chat_id = sub['chat_id']
        notification_time = sub['notification_time']  # This is UTC time from DB

        context.job_queue.run_daily(
            send_daily_notification_job,
            time=notification_time,
            chat_id=chat_id,
            name=str(user_id),
            data=user_id
        )
        count += 1

    logger.info(f"Restored {count} subscriptions from database.")

async def restore_group_price_boards(context: ContextTypes.DEFAULT_TYPE):
    """Restores hourly update jobs for active group price boards on startup."""
    boards = database.get_active_boards()
    count = 0

    for board in boards:
        asset_keys = board['asset_keys'].split(',')
        context.job_queue.run_repeating(
            update_group_price_board_job,
            interval=3600,
            first=60,  # first update 1 minute after startup
            chat_id=board['group_chat_id'],
            name=f"gp_{board['id']}",
            data={
                'board_id': board['id'],
                'group_chat_id': board['group_chat_id'],
                'message_id': board['pinned_message_id'],
                'asset_keys': asset_keys,
            }
        )
        count += 1

    logger.info(f"Restored {count} group price board jobs from database.")

async def update_price_cache_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job to update price cache periodically."""
    price_service.update_cache()

# ---------------------------------------------------------------------------
# Main — application setup
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Initialize Database
    database.init_db()

    if not TOKEN:
        logger.error("Error: TELEGRAM_TOKEN not found in .env file.")
        exit(1)

    # Build Application
    application = ApplicationBuilder().token(TOKEN).build()

    # ConversationHandler for the new /start flow (asset selection → timezone → time)
    start_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            START_ASSET_SELECTION: [
                CallbackQueryHandler(asset_toggle_handler, pattern=r'^asset_toggle_'),
                CallbackQueryHandler(asset_confirm_handler, pattern=r'^asset_confirm$'),
            ],
            START_SELECT_TIMEZONE: [
                CallbackQueryHandler(start_timezone_selected, pattern=r'^tz_'),
            ],
            START_SELECT_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, start_time_received),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True,
    )

    # ConversationHandler for /settings (asset selection only)
    settings_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('settings', settings_command)],
        states={
            SETTINGS_ASSET_SELECTION: [
                CallbackQueryHandler(asset_toggle_handler, pattern=r'^asset_toggle_'),
                CallbackQueryHandler(asset_confirm_handler, pattern=r'^asset_confirm$'),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # Conversation Handler for Adding Subscription (legacy flow via /subscriptions → Add)
    add_sub_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_sub_start, pattern=r'^add_sub$')],
        states={
            SELECT_TIMEZONE: [CallbackQueryHandler(timezone_selected, pattern=r'^tz_')],
            SELECT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # ConversationHandler for /groupprice (asset selection → waiting for group addition)
    groupprice_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('groupprice', groupprice_command)],
        states={
            GP_ASSET_SELECTION: [
                CallbackQueryHandler(asset_toggle_handler, pattern=r'^asset_toggle_'),
                CallbackQueryHandler(asset_confirm_handler, pattern=r'^asset_confirm$'),
            ],
            GP_WAITING_FOR_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gp_waiting_reminder),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, gp_timeout_handler),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        conversation_timeout=1800,  # 30 minutes
    )

    # Add Handlers (order matters — conversation handlers first)
    application.add_handler(start_conv_handler)
    application.add_handler(settings_conv_handler)
    application.add_handler(groupprice_conv_handler)
    application.add_handler(add_sub_conv_handler)
    application.add_handler(CommandHandler('price', price_command))
    application.add_handler(CommandHandler('subscriptions', subscriptions_command))
    application.add_handler(CallbackQueryHandler(remove_single_sub, pattern=r'^remove_sub:'))
    application.add_handler(CallbackQueryHandler(remove_all_subs, pattern=r'^remove_all$'))

    # ChatMemberHandler for detecting bot added to groups
    application.add_handler(
        ChatMemberHandler(bot_added_to_group, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # Restore jobs on startup
    application.job_queue.run_once(restore_jobs, when=0)

    # Restore group price board jobs on startup
    application.job_queue.run_once(restore_group_price_boards, when=2)

    # Schedule background cache update every 15 minutes
    application.job_queue.run_repeating(update_price_cache_job, interval=900, first=1)

    logger.info("Bot is starting...")

    # Run the bot (include all update types for ChatMemberUpdated events)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
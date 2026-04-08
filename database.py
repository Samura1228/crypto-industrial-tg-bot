import sqlite3
import logging
import os
from datetime import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Determine database path
DATA_DIR = os.getenv("DATA_DIR", ".")
DB_NAME = "bot_data.db"
DB_PATH = os.path.join(DATA_DIR, DB_NAME)

# Ensure the directory exists
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR)
    except OSError:
        DB_PATH = DB_NAME

logger.info(f"Using database at: {DB_PATH}")

def init_db():
    """Initialize the database and create the subscriptions table."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create new table with ID primary key to allow multiple subs per user
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                notification_time TEXT NOT NULL,
                timezone TEXT DEFAULT 'UTC',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create user asset preferences table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_asset_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                asset_key TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, asset_key)
            )
        ''')

        # Create group price boards table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_price_boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_chat_id INTEGER,
                pinned_message_id INTEGER,
                asset_keys TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Check if old table exists and migrate
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
        if cursor.fetchone():
            logger.info("Migrating old subscriptions...")
            cursor.execute('SELECT user_id, chat_id, notification_time FROM subscriptions')
            rows = cursor.fetchall()
            for row in rows:
                # Check if already migrated
                cursor.execute('SELECT id FROM subscriptions_v2 WHERE user_id=? AND notification_time=?', (row[0], row[2]))
                if not cursor.fetchone():
                    cursor.execute('INSERT INTO subscriptions_v2 (user_id, chat_id, notification_time) VALUES (?, ?, ?)', row)
            
            # Rename old table to backup (optional, or just leave it)
            cursor.execute('ALTER TABLE subscriptions RENAME TO subscriptions_backup')
            logger.info("Migration complete.")
            
        conn.commit()
        logger.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")
    finally:
        if conn:
            conn.close()

def add_subscription(user_id: int, chat_id: int, notification_time: time, timezone: str = 'UTC'):
    """Add a new subscription for a user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        time_str = notification_time.strftime("%H:%M:%S")
        
        # Check if exact subscription already exists
        cursor.execute('''
            SELECT id FROM subscriptions_v2 
            WHERE user_id = ? AND notification_time = ?
        ''', (user_id, time_str))
        
        if cursor.fetchone():
            logger.info(f"Subscription already exists for user {user_id} at {time_str}")
            return

        cursor.execute('''
            INSERT INTO subscriptions_v2 (user_id, chat_id, notification_time, timezone)
            VALUES (?, ?, ?, ?)
        ''', (user_id, chat_id, time_str, timezone))
        
        conn.commit()
        logger.info(f"Subscription added for user {user_id} at {time_str} ({timezone})")
    except sqlite3.Error as e:
        logger.error(f"Error adding subscription: {e}")
    finally:
        if conn:
            conn.close()

def remove_subscription(user_id: int, notification_time: time = None):
    """Remove a user's subscription(s). If time is None, remove all."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if notification_time:
            time_str = notification_time.strftime("%H:%M:%S")
            cursor.execute('DELETE FROM subscriptions_v2 WHERE user_id = ? AND notification_time = ?', (user_id, time_str))
        else:
            cursor.execute('DELETE FROM subscriptions_v2 WHERE user_id = ?', (user_id,))
            
        conn.commit()
        logger.info(f"Subscription(s) removed for user {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Error removing subscription: {e}")
    finally:
        if conn:
            conn.close()

def get_user_subscriptions(user_id: int):
    """Retrieve all subscriptions for a specific user."""
    subscriptions = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT notification_time, timezone FROM subscriptions_v2 WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        
        for row in rows:
            h, m, s = map(int, row[0].split(':'))
            subscriptions.append({
                'notification_time': time(hour=h, minute=m, second=s),
                'timezone': row[1]
            })
    except sqlite3.Error as e:
        logger.error(f"Error fetching user subscriptions: {e}")
    finally:
        if conn:
            conn.close()
    return subscriptions

def get_user_subscriptions_with_ids(user_id: int):
    """Retrieve all subscriptions for a user, including the database row ID."""
    subscriptions = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, notification_time, timezone FROM subscriptions_v2 WHERE user_id = ? ORDER BY id',
            (user_id,)
        )
        rows = cursor.fetchall()

        for row in rows:
            h, m, s = map(int, row[1].split(':'))
            subscriptions.append({
                'id': row[0],
                'notification_time': time(hour=h, minute=m, second=s),
                'timezone': row[2]
            })
    except sqlite3.Error as e:
        logger.error(f"Error fetching user subscriptions with IDs: {e}")
    finally:
        if conn:
            conn.close()
    return subscriptions

def remove_subscription_by_id(subscription_id: int):
    """Remove a single subscription by its database row ID."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM subscriptions_v2 WHERE id = ?', (subscription_id,))
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"Removed subscription id={subscription_id} (rows affected: {deleted})")
        return deleted > 0
    except sqlite3.Error as e:
        logger.error(f"Error removing subscription by id: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_all_subscriptions():
    """Retrieve all active subscriptions for the scheduler."""
    subscriptions = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, chat_id, notification_time, timezone FROM subscriptions_v2')
        rows = cursor.fetchall()
        
        for row in rows:
            h, m, s = map(int, row[2].split(':'))
            subscriptions.append({
                'user_id': row[0],
                'chat_id': row[1],
                'notification_time': time(hour=h, minute=m, second=s),
                'timezone': row[3]
            })
            
    except sqlite3.Error as e:
        logger.error(f"Error fetching subscriptions: {e}")
    finally:
        if conn:
            conn.close()
    
    return subscriptions
def save_user_assets(user_id: int, asset_keys: list):
    """Save user's selected assets. Deletes old preferences and inserts new ones."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Delete existing preferences for this user
        cursor.execute('DELETE FROM user_asset_preferences WHERE user_id = ?', (user_id,))
        
        # Insert new preferences
        for key in asset_keys:
            cursor.execute(
                'INSERT INTO user_asset_preferences (user_id, asset_key, enabled) VALUES (?, ?, 1)',
                (user_id, key)
            )
        
        conn.commit()
        logger.info(f"Saved {len(asset_keys)} asset preferences for user {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Error saving user assets: {e}")
    finally:
        if conn:
            conn.close()

def get_user_assets(user_id: int):
    """
    Get user's enabled asset keys.
    Returns list of asset_key strings, or None if no preferences exist (backward compat).
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT asset_key FROM user_asset_preferences WHERE user_id = ? AND enabled = 1',
            (user_id,)
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        return [row[0] for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching user assets: {e}")
        return None
    finally:
        if conn:
            conn.close()

def has_asset_preferences(user_id: int) -> bool:
    """Check if user has any asset preferences configured."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM user_asset_preferences WHERE user_id = ?',
            (user_id,)
        )
        count = cursor.fetchone()[0]
        return count > 0
    except sqlite3.Error as e:
        logger.error(f"Error checking user asset preferences: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ---------------------------------------------------------------------------
# Group Price Board functions
# ---------------------------------------------------------------------------

def create_group_price_board(user_id: int, asset_keys: list) -> int:
    """Insert a new pending group price board. Cancels any existing pending boards first.
    Returns the row id."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Cancel any existing pending boards for this user
        cursor.execute(
            "UPDATE group_price_boards SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        )

        # Insert new pending board
        asset_keys_str = ','.join(asset_keys)
        cursor.execute(
            "INSERT INTO group_price_boards (user_id, asset_keys, status) VALUES (?, ?, 'pending')",
            (user_id, asset_keys_str)
        )
        conn.commit()
        board_id = cursor.lastrowid
        logger.info(f"Created group price board {board_id} for user {user_id} with {len(asset_keys)} assets")
        return board_id
    except sqlite3.Error as e:
        logger.error(f"Error creating group price board: {e}")
        return -1
    finally:
        if conn:
            conn.close()


def get_pending_board_for_user(user_id: int):
    """Get the most recent pending or awaiting_admin board for a user.
    Returns dict with keys: id, user_id, asset_keys, status, group_chat_id, created_at, or None.

    This matches both 'pending' (board created, bot not yet added to any group)
    and 'awaiting_admin' (bot was added to a group but user hasn't confirmed admin yet).
    The latter case allows the bot to update the group_chat_id if the user removes
    the bot from one group and adds it to another.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM group_price_boards WHERE user_id = ? AND status IN ('pending', 'awaiting_admin') "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except sqlite3.Error as e:
        logger.error(f"Error fetching pending/awaiting_admin board for user {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()


def activate_group_price_board(board_id: int, group_chat_id: int, pinned_message_id: int):
    """Activate a pending board: set status to 'active', fill in group_chat_id and pinned_message_id."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE group_price_boards SET status = 'active', group_chat_id = ?, "
            "pinned_message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (group_chat_id, pinned_message_id, board_id)
        )
        conn.commit()
        logger.info(f"Activated group price board {board_id} for group {group_chat_id}")
    except sqlite3.Error as e:
        logger.error(f"Error activating group price board {board_id}: {e}")
    finally:
        if conn:
            conn.close()


def get_active_boards():
    """Get all active group price boards (for job restoration on startup).
    Returns list of dicts."""
    boards = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM group_price_boards WHERE status = 'active'")
        rows = cursor.fetchall()
        boards = [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching active boards: {e}")
    finally:
        if conn:
            conn.close()
    return boards


def get_board_by_group(group_chat_id: int):
    """Look up the active board for a specific group chat.
    Returns dict or None."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM group_price_boards WHERE group_chat_id = ? AND status = 'active' LIMIT 1",
            (group_chat_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except sqlite3.Error as e:
        logger.error(f"Error fetching board for group {group_chat_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()


def deactivate_board(board_id: int):
    """Set a board's status to 'inactive'."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE group_price_boards SET status = 'inactive', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (board_id,)
        )
        conn.commit()
        logger.info(f"Deactivated group price board {board_id}")
    except sqlite3.Error as e:
        logger.error(f"Error deactivating board {board_id}: {e}")
    finally:
        if conn:
            conn.close()


def update_pinned_message_id(board_id: int, message_id: int):
    """Update the pinned message ID for a board."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE group_price_boards SET pinned_message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (message_id, board_id)
        )
        conn.commit()
        logger.info(f"Updated pinned message ID for board {board_id} to {message_id}")
    except sqlite3.Error as e:
        logger.error(f"Error updating pinned message ID for board {board_id}: {e}")
    finally:
        if conn:
            conn.close()


def cancel_pending_boards(user_id: int):
    """Cancel any existing pending or awaiting_admin boards for a user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE group_price_boards SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND status IN ('pending', 'awaiting_admin')",
            (user_id,)
        )
        conn.commit()
        affected = cursor.rowcount
        if affected > 0:
            logger.info(f"Cancelled {affected} pending/awaiting_admin board(s) for user {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Error cancelling pending boards for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()


def set_board_awaiting_admin(board_id: int, group_chat_id: int):
    """Update a pending board with the group_chat_id and set status to 'awaiting_admin'."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE group_price_boards SET group_chat_id = ?, status = 'awaiting_admin', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (group_chat_id, board_id)
        )
        conn.commit()
        logger.info(f"Board {board_id} set to awaiting_admin with group_chat_id={group_chat_id}")
    except sqlite3.Error as e:
        logger.error(f"Error setting board {board_id} to awaiting_admin: {e}")
    finally:
        if conn:
            conn.close()


def get_awaiting_admin_board_for_user(user_id: int):
    """Get the most recent awaiting_admin board for a user.
    Returns dict with keys: id, user_id, group_chat_id, asset_keys, status, etc., or None."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM group_price_boards WHERE user_id = ? AND status = 'awaiting_admin' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except sqlite3.Error as e:
        logger.error(f"Error fetching awaiting_admin board for user {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()
def get_all_user_ids() -> list[int]:
    """Return all unique user_ids from the subscriptions_v2 table."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM subscriptions_v2')
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching all user IDs: {e}")
        return []
    finally:
        if conn:
            conn.close()
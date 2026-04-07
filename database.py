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
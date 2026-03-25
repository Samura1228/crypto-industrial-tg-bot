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
# Check for DATA_DIR environment variable (e.g., for Railway Volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
DB_NAME = "bot_data.db"
DB_PATH = os.path.join(DATA_DIR, DB_NAME)

# Ensure the directory exists
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR)
        logger.info(f"Created data directory: {DATA_DIR}")
    except OSError as e:
        logger.error(f"Error creating data directory {DATA_DIR}: {e}")
        # Fallback to current directory if creation fails
        DB_PATH = DB_NAME

logger.info(f"Using database at: {DB_PATH}")

def init_db():
    """Initialize the database and create the subscriptions table if it doesn't exist."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                notification_time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")
    finally:
        if conn:
            conn.close()

def add_subscription(user_id: int, chat_id: int, notification_time: time):
    """Add or update a user's subscription."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Store time as string "HH:MM:SS"
        time_str = notification_time.strftime("%H:%M:%S")
        
        cursor.execute('''
            INSERT OR REPLACE INTO subscriptions (user_id, chat_id, notification_time)
            VALUES (?, ?, ?)
        ''', (user_id, chat_id, time_str))
        
        conn.commit()
        logger.info(f"Subscription added/updated for user {user_id} at {time_str}")
    except sqlite3.Error as e:
        logger.error(f"Error adding subscription: {e}")
    finally:
        if conn:
            conn.close()

def remove_subscription(user_id: int):
    """Remove a user's subscription."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
        conn.commit()
        logger.info(f"Subscription removed for user {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Error removing subscription: {e}")
    finally:
        if conn:
            conn.close()

def get_all_subscriptions():
    """Retrieve all active subscriptions."""
    subscriptions = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, chat_id, notification_time FROM subscriptions')
        rows = cursor.fetchall()
        
        for row in rows:
            # Convert time string back to time object
            h, m, s = map(int, row[2].split(':'))
            subscriptions.append({
                'user_id': row[0],
                'chat_id': row[1],
                'notification_time': time(hour=h, minute=m, second=s)
            })
            
    except sqlite3.Error as e:
        logger.error(f"Error fetching subscriptions: {e}")
    finally:
        if conn:
            conn.close()
    
    return subscriptions
import sqlite3
import logging
from datetime import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_NAME = "bot_data.db"

def init_db():
    """Initialize the database and create the subscriptions table if it doesn't exist."""
    try:
        conn = sqlite3.connect(DB_NAME)
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
    try:
        conn = sqlite3.connect(DB_NAME)
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
    try:
        conn = sqlite3.connect(DB_NAME)
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
    try:
        conn = sqlite3.connect(DB_NAME)
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
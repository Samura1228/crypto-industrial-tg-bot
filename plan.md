# Telegram Crypto & Metal Notifier Bot Plan

## 📋 Project Overview
A Telegram bot that sends daily price notifications for selected Cryptocurrencies and Industrial Metals. Users subscribe by starting the bot, and the bot schedules a daily message at that exact time.

## 🏗️ Architecture
*   **Language:** Python 3.11+
*   **Bot Framework:** `python-telegram-bot` (v20+) - Robust, async, and feature-rich.
*   **Database:** `SQLite` - Simple, file-based storage for user subscriptions.
    *   *Railway Note:* Requires a Persistent Volume to retain data across restarts.
*   **Hosting:** Railway (via Docker).

## 🔌 Data Sources
We will use the **CryptoCompare API** for all data points.
*   **Crypto:** Bitcoin (BTC), Ethereum (ETH), Toncoin (TON), Solana (SOL).
*   **Metals:** Gold (XAU), Silver (XAG).

## 🗄️ Database Schema
**Table:** `subscriptions`
| Column | Type | Description |
| :--- | :--- | :--- |
| `user_id` | INTEGER | Primary Key (Telegram User ID) |
| `chat_id` | INTEGER | Telegram Chat ID (usually same as User ID for DMs) |
| `notification_time` | TEXT | Time of day to send notification (HH:MM format, UTC) |
| `created_at` | TEXT | Timestamp of subscription |

## 🤖 Bot Logic

### 1. `/start` Handler
*   **Trigger:** User clicks "Start" or types `/start`.
*   **Action:**
    1.  Get the current time.
    2.  Save `user_id`, `chat_id`, and `notification_time` to the SQLite database.
    3.  Schedule a recurring daily job using `JobQueue` for this specific time.
    4.  Reply to user: "✅ You will receive a notification every day at this time."

### 2. Notification Job
*   **Trigger:** Scheduled time (Daily).
*   **Action:**
    1.  Fetch current prices for BTC, ETH, TON, SOL, XAU, XAG from CryptoCompare.
    2.  Format the message with emojis and clear pricing.
    3.  Send the message to the user.

### 3. Startup / Restart Logic
*   **Trigger:** Bot application starts (or restarts after deployment).
*   **Action:**
    1.  Initialize the database connection.
    2.  Fetch all active subscriptions from the `subscriptions` table.
    3.  Re-schedule the daily jobs for each user based on their stored `notification_time`.

## 🚀 Deployment (Railway)
*   **Dockerfile:** Python 3.11 base image.
*   **Environment Variables:**
    *   `TELEGRAM_TOKEN`: Your Bot Token.
    *   `CRYPTOCOMPARE_API_KEY`: Your API Key.
*   **Persistence:** Configure a Railway Volume to mount at `/app/data` (or similar) to store `bot.db`.

## 📅 Implementation Steps
1.  **Setup:** Initialize project, `requirements.txt`, `.env`.
2.  **Data Service:** Create `price_service.py` to fetch and format prices.
3.  **Database:** Create `database.py` to handle SQLite operations.
4.  **Bot Core:** Create `bot.py` with `/start` handler and `JobQueue` setup.
5.  **Docker:** Create `Dockerfile` for deployment.
6.  **Testing:** Run locally to verify functionality.
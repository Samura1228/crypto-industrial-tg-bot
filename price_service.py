import os
import requests
import logging
import csv
import io
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")
AV_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
BASE_URL = "https://min-api.cryptocompare.com/data/pricemultifull"

# Global cache
_cache = {
    "crypto": {},
    "oil": {"WTI": {"price": None, "change": None}, "Brent": {"price": None, "change": None}},
    "forex": {"USD": {"price": None, "change": None}, "EUR": {"price": None, "change": None}},
    "last_updated": 0
}

def format_price(price, symbol="$"):
    if price is None:
        return "N/A"
    try:
        return f"{symbol}{float(price):,.2f}"
    except (ValueError, TypeError):
        return "N/A"

def get_arrow(change):
    """Returns an arrow emoji based on price change."""
    if change is None:
        return ""
    try:
        change = float(change)
        if change > 0:
            return "⬆️"
        elif change < 0:
            return "⬇️"
        else:
            return ""
    except (ValueError, TypeError):
        return ""

def get_av_data(function, symbol=None, from_curr=None, to_curr=None):
    """Helper to fetch data from Alpha Vantage with error handling."""
    if not AV_API_KEY: return None
    
    url = f"https://www.alphavantage.co/query?function={function}&apikey={AV_API_KEY}"
    if symbol: url += f"&symbol={symbol}"
    if from_curr: url += f"&from_currency={from_curr}"
    if to_curr: url += f"&to_currency={to_curr}"
    if function in ["WTI", "BRENT"]: url += "&interval=daily"
    
    try:
        r = requests.get(url)
        d = r.json()
        if "Note" in d:
            logger.warning(f"Alpha Vantage Rate Limit: {d['Note']}")
            return None
        return d
    except Exception as e:
        logger.error(f"Alpha Vantage error: {e}")
        return None

def update_cache():
    """
    Fetches all data and updates the global cache.
    This function takes time (30s+) due to rate limits.
    """
    logger.info("Updating price cache...")
    
    # 1. Fetch Crypto + Metals + EUR/USD (CryptoCompare)
    fsyms = "BTC,ETH,TON,SOL,PAXG,KAG,EUR"
    tsyms = "USD"
    url = f"{BASE_URL}?fsyms={fsyms}&tsyms={tsyms}&api_key={API_KEY}"
    
    eur_usd_rate = None
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "RAW" in data:
            for symbol in ["BTC", "ETH", "TON", "SOL", "PAXG", "KAG", "EUR"]:
                try:
                    price = data["RAW"][symbol]["USD"]["PRICE"]
                    change = data["RAW"][symbol]["USD"]["CHANGE24HOUR"]
                    _cache["crypto"][symbol] = {"price": price, "change": change}
                    if symbol == "EUR":
                        eur_usd_rate = price
                except KeyError:
                    pass
    except Exception as e:
        logger.error(f"Error fetching crypto data: {e}")

    # 2. Fetch WTI (Alpha Vantage)
    wti_data = get_av_data("WTI")
    if wti_data and "data" in wti_data and len(wti_data["data"]) > 0:
        latest = wti_data["data"][0]
        price = float(latest["value"])
        prev = float(wti_data["data"][1]["value"]) if len(wti_data["data"]) > 1 else price
        _cache["oil"]["WTI"] = {"price": price, "change": price - prev}
    
    time.sleep(15) # Rate limit delay

    # 3. Fetch Brent (Alpha Vantage)
    brent_data = get_av_data("BRENT")
    if brent_data and "data" in brent_data and len(brent_data["data"]) > 0:
        latest = brent_data["data"][0]
        price = float(latest["value"])
        prev = float(brent_data["data"][1]["value"]) if len(brent_data["data"]) > 1 else price
        _cache["oil"]["Brent"] = {"price": price, "change": price - prev}

    time.sleep(15) # Rate limit delay

    # 4. Fetch USD/RUB (Alpha Vantage)
    av_forex = get_av_data("CURRENCY_EXCHANGE_RATE", from_curr="USD", to_curr="RUB")
    if av_forex and "Realtime Currency Exchange Rate" in av_forex:
        rate = av_forex["Realtime Currency Exchange Rate"]
        usd_rub = float(rate["5. Exchange Rate"])
        _cache["forex"]["USD"] = {"price": usd_rub, "change": 0}
        
        # Calculate EUR/RUB
        if eur_usd_rate:
            _cache["forex"]["EUR"] = {"price": usd_rub * eur_usd_rate, "change": 0}

    _cache["last_updated"] = time.time()
    logger.info("Price cache updated.")

def get_prices():
    """
    Returns the formatted message from cache.
    If cache is empty, triggers an update (blocking).
    """
    if _cache["last_updated"] == 0:
        update_cache()
    
    c = _cache["crypto"]
    o = _cache["oil"]
    f = _cache["forex"]

    def p(data, currency_symbol="$"):
        if not data or data.get("price") is None: return "N/A"
        price = format_price(data.get("price"), currency_symbol)
        arrow = get_arrow(data.get("change"))
        return f"{price}{arrow}"

    message = (
        "📊 **Daily Market Update** 📊\n\n"
        "**Crypto:**\n"
        f"₿ **Bitcoin (BTC):** {p(c.get('BTC'))}\n"
        f"💎 **Ethereum (ETH):** {p(c.get('ETH'))}\n"
        f"💎 **Toncoin (TON):** {p(c.get('TON'))}\n"
        f"☀️ **Solana (SOL):** {p(c.get('SOL'))}\n\n"
        "**Metals (1 oz):**\n"
        f"🟡 **Gold (PAXG):** {p(c.get('PAXG'))}\n"
        f"⚪ **Silver (KAG):** {p(c.get('KAG'))}\n\n"
        "**Oil (Barrel):**\n"
        f"🛢️ **WTI Crude:** {p(o.get('WTI'))}\n"
        f"🛢️ **Brent Crude:** {p(o.get('Brent'))}\n\n"
        "**Currencies (RUB):**\n"
        f"🇺🇸 **USD/RUB:** {p(f.get('USD'), '₽')}\n"
        f"🇪🇺 **EUR/RUB:** {p(f.get('EUR'), '₽')}\n"
    )
    
    return message

if __name__ == "__main__":
    print(get_prices())
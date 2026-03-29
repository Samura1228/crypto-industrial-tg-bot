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

# Cache to avoid rate limits
# Cache for 30 minutes
CACHE_DURATION = 1800 
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

def get_yfinance_data(symbol):
    """Helper to fetch data from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            meta = data["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            prev = float(meta["previousClose"])
            return {"price": price, "change": price - prev}
        else:
            logger.warning(f"Yahoo Finance returned status code {r.status_code} for {symbol}")
    except Exception as e:
        logger.error(f"Yahoo Finance error for {symbol}: {e}")
    return None

def update_cache():
    """
    Fetches all data and updates the global cache.
    """
    logger.info("Updating price cache...")
    
    # 1. Fetch Crypto + Metals (CryptoCompare)
    fsyms = "BTC,ETH,TON,SOL,PAXG,KAG"
    tsyms = "USD"
    url = f"{BASE_URL}?fsyms={fsyms}&tsyms={tsyms}&api_key={API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "RAW" in data:
            for symbol in ["BTC", "ETH", "TON", "SOL", "PAXG", "KAG"]:
                try:
                    price = data["RAW"][symbol]["USD"]["PRICE"]
                    change = data["RAW"][symbol]["USD"]["CHANGE24HOUR"]
                    _cache["crypto"][symbol] = {"price": price, "change": change}
                except KeyError:
                    pass
    except Exception as e:
        logger.error(f"Error fetching crypto data: {e}")

    # 2. Fetch Forex (FloatRates - Free, No Key)
    try:
        url = "http://www.floatrates.com/daily/usd.json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            d = r.json()
            if "rub" in d:
                usd_rub = float(d["rub"]["rate"])
                # FloatRates gives inverse rate sometimes? No, rate is per 1 USD.
                # Change? FloatRates gives 'inverseRate', 'date'. No 24h change.
                # We'll assume 0 change or calculate if we had history.
                _cache["forex"]["USD"] = {"price": usd_rub, "change": 0}
                
                if "eur" in d:
                    usd_eur = float(d["eur"]["rate"])
                    # EUR/RUB = USD/RUB / USD/EUR
                    eur_rub = usd_rub / usd_eur
                    _cache["forex"]["EUR"] = {"price": eur_rub, "change": 0}
    except Exception as e:
        logger.error(f"FloatRates error: {e}")

    # 3. Fetch WTI (Yahoo Finance)
    wti_data = get_yfinance_data("CL=F")
    if wti_data:
        _cache["oil"]["WTI"] = wti_data
    
    # 4. Fetch Brent (Yahoo Finance)
    brent_data = get_yfinance_data("BZ=F")
    if brent_data:
        _cache["oil"]["Brent"] = brent_data

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
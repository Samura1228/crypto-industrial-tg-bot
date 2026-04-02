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

# Asset Registry — canonical list of all tracked assets
ASSET_REGISTRY = [
    {"key": "BTC",     "emoji": "₿",  "label": "Bitcoin (BTC)",    "category": "Crypto",      "currency_symbol": "$"},
    {"key": "ETH",     "emoji": "💎", "label": "Ethereum (ETH)",   "category": "Crypto",      "currency_symbol": "$"},
    {"key": "TON",     "emoji": "💎", "label": "Toncoin (TON)",    "category": "Crypto",      "currency_symbol": "$"},
    {"key": "SOL",     "emoji": "☀️", "label": "Solana (SOL)",     "category": "Crypto",      "currency_symbol": "$"},
    {"key": "PAXG",    "emoji": "🟡", "label": "Gold (PAXG)",      "category": "Metals (1 oz)", "currency_symbol": "$"},
    {"key": "KAG",     "emoji": "⚪", "label": "Silver (KAG)",     "category": "Metals (1 oz)", "currency_symbol": "$"},
    {"key": "WTI",     "emoji": "🛢️", "label": "WTI Crude",        "category": "Oil (Barrel)", "currency_symbol": "$"},
    {"key": "BRENT",   "emoji": "🛢️", "label": "Brent Crude",      "category": "Oil (Barrel)", "currency_symbol": "$"},
    {"key": "USD_RUB", "emoji": "🇺🇸", "label": "USD/RUB",         "category": "Currencies (RUB)", "currency_symbol": "₽"},
    {"key": "EUR_RUB", "emoji": "🇪🇺", "label": "EUR/RUB",         "category": "Currencies (RUB)", "currency_symbol": "₽"},
]

ALL_ASSET_KEYS = [a["key"] for a in ASSET_REGISTRY]

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

def _get_asset_price_data(key):
    """Maps an asset key to its cached price data."""
    c = _cache["crypto"]
    o = _cache["oil"]
    f = _cache["forex"]
    mapping = {
        "BTC": c.get("BTC"),
        "ETH": c.get("ETH"),
        "TON": c.get("TON"),
        "SOL": c.get("SOL"),
        "PAXG": c.get("PAXG"),
        "KAG": c.get("KAG"),
        "WTI": o.get("WTI"),
        "BRENT": o.get("Brent"),
        "USD_RUB": f.get("USD"),
        "EUR_RUB": f.get("EUR"),
    }
    return mapping.get(key)

def get_filtered_prices(asset_keys):
    """
    Returns formatted message with only the specified assets.
    Category headers are only shown if at least one asset in that category is selected.
    """
    if _cache["last_updated"] == 0:
        update_cache()

    def p(data, currency_symbol="$"):
        if not data or data.get("price") is None:
            return "N/A"
        price = format_price(data.get("price"), currency_symbol)
        arrow = get_arrow(data.get("change"))
        return f"{price}{arrow}"

    asset_keys_set = set(asset_keys)
    
    # Group assets by category, preserving registry order
    from collections import OrderedDict
    categories = OrderedDict()
    for asset in ASSET_REGISTRY:
        if asset["key"] in asset_keys_set:
            cat = asset["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(asset)

    message = "📊 **Daily Market Update** 📊\n\n"
    
    for cat, assets in categories.items():
        message += f"**{cat}:**\n"
        for asset in assets:
            data = _get_asset_price_data(asset["key"])
            price_str = p(data, asset["currency_symbol"])
            message += f"{asset['emoji']} **{asset['label']}:** {price_str}\n"
        message += "\n"

    return message

def get_prices():
    """
    Returns formatted message with ALL assets (backward compatible).
    """
    return get_filtered_prices(ALL_ASSET_KEYS)

if __name__ == "__main__":
    print(get_prices())
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

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
AV_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Mapping from internal symbol -> CoinGecko ID
COINGECKO_ID_MAP = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "TON":  "the-open-network",
    "SOL":  "solana",
    "PAXG": "pax-gold",
    "KAG":  "kinesis-silver",
}
# Reverse mapping CoinGecko ID -> internal symbol
COINGECKO_ID_TO_SYMBOL = {v: k for k, v in COINGECKO_ID_MAP.items()}

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
    {"key": "sp500",   "emoji": "📈", "label": "S&P 500",          "category": "Indices",      "currency_symbol": "$"},
    {"key": "nasdaq",  "emoji": "📊", "label": "NASDAQ",           "category": "Indices",      "currency_symbol": "$"},
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
    "indices": {"sp500": {"price": None, "change": None}, "nasdaq": {"price": None, "change": None}},
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

    # 1. Fetch Crypto + Metals (CoinGecko)
    expected_symbols = ["BTC", "ETH", "TON", "SOL", "PAXG", "KAG"]
    ids_param = ",".join(COINGECKO_ID_MAP[sym] for sym in expected_symbols)

    if not COINGECKO_API_KEY:
        logger.error(
            "COINGECKO_API_KEY is missing from environment! "
            "CoinGecko may rate-limit or reject requests."
        )

    # Snapshot pre-fetch crypto cache so we can detect stale (un-refreshed) entries
    crypto_before = {
        sym: (_cache["crypto"].get(sym) or {}).get("price")
        for sym in expected_symbols
    }
    refreshed_symbols: set = set()

    headers = {
        "accept": "application/json",
    }
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    params = {
        "ids": ids_param,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }

    logger.info(
        f"CoinGecko request: ids={ids_param} vs_currencies=usd "
        f"(api_key={'set' if COINGECKO_API_KEY else 'MISSING'})"
    )

    try:
        response = requests.get(COINGECKO_URL, headers=headers, params=params, timeout=15)
        logger.info(f"CoinGecko HTTP status: {response.status_code}")

        if response.status_code == 429:
            logger.error(
                "CoinGecko rate limit (429) hit — crypto prices will NOT be refreshed this cycle. "
                f"Body (truncated): {response.text[:500]}"
            )
        elif response.status_code != 200:
            logger.error(
                f"CoinGecko returned non-200 status {response.status_code}. "
                f"Body (truncated): {response.text[:500]}"
            )
        else:
            try:
                data = response.json()
            except ValueError as je:
                logger.error(
                    f"CoinGecko returned non-JSON response: {je}. "
                    f"Body (truncated): {response.text[:500]}"
                )
                data = {}

            if not isinstance(data, dict) or not data:
                logger.error(
                    "CoinGecko response empty or unexpected shape — "
                    "crypto prices will NOT be refreshed. "
                    f"Body (truncated): {str(data)[:500]}"
                )
            else:
                for symbol in expected_symbols:
                    cg_id = COINGECKO_ID_MAP[symbol]
                    entry = data.get(cg_id)
                    if not entry or "usd" not in entry:
                        logger.warning(
                            f"CoinGecko payload missing data for {symbol} (id={cg_id}). "
                            "Symbol will keep its previous cached value."
                        )
                        continue
                    try:
                        price = float(entry["usd"])
                        # 24h change as percentage; existing get_arrow() works off sign.
                        change_pct = entry.get("usd_24h_change")
                        change_val = float(change_pct) if change_pct is not None else 0.0
                        _cache["crypto"][symbol] = {"price": price, "change": change_val}
                        refreshed_symbols.add(symbol)
                    except (TypeError, ValueError) as ve:
                        logger.warning(
                            f"CoinGecko payload had invalid numeric data for {symbol} "
                            f"({ve!r}). Symbol will keep its previous cached value."
                        )
    except requests.exceptions.Timeout:
        logger.error("CoinGecko request timed out after 15s — crypto cache not refreshed.")
    except requests.exceptions.RequestException as e:
        logger.error(f"CoinGecko network/request error: {e!r}")
    except Exception as e:
        logger.exception(f"Unexpected error fetching crypto data: {e!r}")

    # Stale-cache detection: report any expected symbol that wasn't refreshed this cycle.
    stale_symbols = [s for s in expected_symbols if s not in refreshed_symbols]
    if stale_symbols:
        details = []
        for sym in stale_symbols:
            prev_price = crypto_before.get(sym)
            details.append(f"{sym}={prev_price}")
        logger.warning(
            "STALE CRYPTO CACHE: the following symbols were NOT refreshed this cycle "
            f"and will keep previous values: {', '.join(details)}. "
            "Investigate CoinGecko API health / rate limits / API key validity."
        )
    else:
        logger.info(
            f"Crypto cache successfully refreshed for all {len(refreshed_symbols)} symbols: "
            f"{sorted(refreshed_symbols)}"
        )

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

    # 5. Fetch S&P 500 (Yahoo Finance)
    sp500_data = get_yfinance_data("^GSPC")
    if sp500_data:
        _cache["indices"]["sp500"] = sp500_data

    # 6. Fetch NASDAQ Composite (Yahoo Finance)
    nasdaq_data = get_yfinance_data("^IXIC")
    if nasdaq_data:
        _cache["indices"]["nasdaq"] = nasdaq_data

    _cache["last_updated"] = time.time()
    logger.info("Price cache updated.")

def _get_asset_price_data(key):
    """Maps an asset key to its cached price data."""
    c = _cache["crypto"]
    o = _cache["oil"]
    i = _cache["indices"]
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
        "sp500": i.get("sp500"),
        "nasdaq": i.get("nasdaq"),
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
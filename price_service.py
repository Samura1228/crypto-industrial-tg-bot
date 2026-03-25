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

# Cache to avoid rate limits (Alpha Vantage: 5 req/min, 500/day)
# Cache for 30 minutes
CACHE_DURATION = 1800 
_price_cache = {
    "oil": {"data": None, "timestamp": 0},
    "forex": {"data": None, "timestamp": 0}
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

def get_forex_prices():
    """
    Fetches USD/RUB and EUR/RUB prices.
    Tries Alpha Vantage first (if key exists), then Stooq.
    """
    # Check cache
    if time.time() - _price_cache["forex"]["timestamp"] < CACHE_DURATION and _price_cache["forex"]["data"]:
        return _price_cache["forex"]["data"]

    data = {"USD": {"price": None, "change": None}, "EUR": {"price": None, "change": None}}
    
    # Try Alpha Vantage if key is present
    if AV_API_KEY:
        try:
            # USD/RUB
            url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=USD&to_currency=RUB&apikey={AV_API_KEY}"
            r = requests.get(url)
            d = r.json()
            if "Realtime Currency Exchange Rate" in d:
                rate = d["Realtime Currency Exchange Rate"]
                price = float(rate["5. Exchange Rate"])
                data["USD"]["price"] = price
                data["USD"]["change"] = 0
            elif "Note" in d:
                logger.warning(f"Alpha Vantage Rate Limit (USD/RUB): {d['Note']}")
            
            # Wait to respect rate limit (5 req/min = 1 req/12s)
            time.sleep(12)

            # EUR/RUB
            url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=EUR&to_currency=RUB&apikey={AV_API_KEY}"
            r = requests.get(url)
            d = r.json()
            if "Realtime Currency Exchange Rate" in d:
                rate = d["Realtime Currency Exchange Rate"]
                price = float(rate["5. Exchange Rate"])
                data["EUR"]["price"] = price
                data["EUR"]["change"] = 0
            elif "Note" in d:
                logger.warning(f"Alpha Vantage Rate Limit (EUR/RUB): {d['Note']}")

            # Update cache if we got data
            if data["USD"]["price"] and data["EUR"]["price"]:
                _price_cache["forex"] = {"data": data, "timestamp": time.time()}
                return data
                
        except Exception as e:
            logger.error(f"Alpha Vantage Forex error: {e}")

    # Fallback to Stooq (might fail on Railway)
    symbols = {"USD": "USDRUB", "EUR": "EURRUB"}
    for name, sym in symbols.items():
        if data[name]["price"] is not None: continue # Skip if already found
        try:
            url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlc&h&e=csv"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                f = io.StringIO(response.text)
                reader = csv.reader(f)
                next(reader) # Skip header
                row = next(reader)
                if len(row) >= 7:
                    try:
                        close_price = float(row[6])
                        open_price = float(row[3])
                        data[name]["price"] = close_price
                        data[name]["change"] = close_price - open_price
                    except: pass
        except Exception as e:
            logger.error(f"Stooq Forex error for {name}: {e}")
            
    return data

def get_oil_prices():
    """
    Fetches WTI and Brent Crude Oil prices.
    Tries Alpha Vantage first (if key exists), then Stooq.
    """
    # Check cache
    if time.time() - _price_cache["oil"]["timestamp"] < CACHE_DURATION and _price_cache["oil"]["data"]:
        return _price_cache["oil"]["data"]

    data = {"WTI": {"price": None, "change": None}, "Brent": {"price": None, "change": None}}
    
    # Try Alpha Vantage if key is present
    if AV_API_KEY:
        try:
            # WTI
            url = f"https://www.alphavantage.co/query?function=WTI&interval=daily&apikey={AV_API_KEY}"
            r = requests.get(url)
            d = r.json()
            if "data" in d and len(d["data"]) > 0:
                latest = d["data"][0]
                price = float(latest["value"])
                if len(d["data"]) > 1:
                    prev = float(d["data"][1]["value"])
                    change = price - prev
                else:
                    change = 0
                data["WTI"]["price"] = price
                data["WTI"]["change"] = change
            elif "Note" in d:
                logger.warning(f"Alpha Vantage Rate Limit (WTI): {d['Note']}")
            
            # Wait to respect rate limit
            time.sleep(12)

            # Brent
            url = f"https://www.alphavantage.co/query?function=BRENT&interval=daily&apikey={AV_API_KEY}"
            r = requests.get(url)
            d = r.json()
            if "data" in d and len(d["data"]) > 0:
                latest = d["data"][0]
                price = float(latest["value"])
                if len(d["data"]) > 1:
                    prev = float(d["data"][1]["value"])
                    change = price - prev
                else:
                    change = 0
                data["Brent"]["price"] = price
                data["Brent"]["change"] = change
            elif "Note" in d:
                logger.warning(f"Alpha Vantage Rate Limit (Brent): {d['Note']}")

            # Update cache if we got data
            if data["WTI"]["price"] and data["Brent"]["price"]:
                _price_cache["oil"] = {"data": data, "timestamp": time.time()}
                return data

        except Exception as e:
            logger.error(f"Alpha Vantage Oil error: {e}")

    # Fallback to Stooq
    symbols = {"WTI": "CL.F", "Brent": "CB.F"}
    for name, sym in symbols.items():
        if data[name]["price"] is not None: continue
        try:
            url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlc&h&e=csv"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                f = io.StringIO(response.text)
                reader = csv.reader(f)
                next(reader)
                row = next(reader)
                if len(row) >= 7:
                    try:
                        close_price = float(row[6])
                        open_price = float(row[3])
                        data[name]["price"] = close_price
                        data[name]["change"] = close_price - open_price
                    except: pass
        except Exception as e:
            logger.error(f"Stooq Oil error for {name}: {e}")
            
    return data

def get_prices():
    """
    Fetches current prices for BTC, ETH, TON, SOL, Gold (PAXG), Silver (KAG), Oil, and Forex.
    Returns a formatted string message with trend arrows.
    """
    # PAXG = Pax Gold (1 oz Gold backed token)
    # KAG = Kinesis Silver (1 oz Silver backed token)
    fsyms = "BTC,ETH,TON,SOL,PAXG,KAG"
    tsyms = "USD"
    url = f"{BASE_URL}?fsyms={fsyms}&tsyms={tsyms}&api_key={API_KEY}"
    
    crypto_data = {}
    oil_data = get_oil_prices()
    forex_data = get_forex_prices()
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "RAW" in data:
            for symbol in ["BTC", "ETH", "TON", "SOL", "PAXG", "KAG"]:
                try:
                    price = data["RAW"][symbol]["USD"]["PRICE"]
                    change = data["RAW"][symbol]["USD"]["CHANGE24HOUR"]
                    crypto_data[symbol] = {"price": price, "change": change}
                except KeyError:
                    crypto_data[symbol] = {"price": None, "change": None}
        else:
            logger.error(f"Error fetching crypto data: {data}")

        # Helper to get formatted string "Price ⬆️"
        def p(symbol_data, currency_symbol="$"):
            if not symbol_data: return "N/A"
            price = format_price(symbol_data.get("price"), currency_symbol)
            arrow = get_arrow(symbol_data.get("change"))
            return f"{price}{arrow}"

        # Construct the message
        message = (
            "📊 **Daily Market Update** 📊\n\n"
            "**Crypto:**\n"
            f"₿ **Bitcoin (BTC):** {p(crypto_data.get('BTC'))}\n"
            f"💎 **Ethereum (ETH):** {p(crypto_data.get('ETH'))}\n"
            f"💎 **Toncoin (TON):** {p(crypto_data.get('TON'))}\n"
            f"☀️ **Solana (SOL):** {p(crypto_data.get('SOL'))}\n\n"
            "**Metals (1 oz):**\n"
            f"🟡 **Gold (PAXG):** {p(crypto_data.get('PAXG'))}\n"
            f"⚪ **Silver (KAG):** {p(crypto_data.get('KAG'))}\n\n"
            "**Oil (Barrel):**\n"
            f"🛢️ **WTI Crude:** {p(oil_data.get('WTI'))}\n"
            f"🛢️ **Brent Crude:** {p(oil_data.get('Brent'))}\n\n"
            "**Currencies (RUB):**\n"
            f"🇺🇸 **USD/RUB:** {p(forex_data.get('USD'), '₽')}\n"
            f"🇪🇺 **EUR/RUB:** {p(forex_data.get('EUR'), '₽')}\n"
        )
        
        return message

    except Exception as e:
        logger.error(f"Exception in get_prices: {e}")
        return "⚠️ An error occurred while fetching market data."

if __name__ == "__main__":
    # Test the function locally
    print(get_prices())
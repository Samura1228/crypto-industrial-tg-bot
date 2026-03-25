import os
import requests
import logging
import csv
import io
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
BASE_URL = "https://min-api.cryptocompare.com/data/pricemultifull"

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
    Fetches USD/RUB and EUR/RUB prices from Stooq.
    Returns a dictionary with 'USD' and 'EUR' data (price, change).
    """
    data = {"USD": {"price": None, "change": None}, "EUR": {"price": None, "change": None}}
    symbols = {"USD": "USDRUB", "EUR": "EURRUB"}
    
    for name, sym in symbols.items():
        try:
            url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlc&h&e=csv"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                f = io.StringIO(response.text)
                reader = csv.reader(f)
                header = next(reader) # Skip header
                row = next(reader)    # Get data row
                
                if len(row) >= 7:
                    try:
                        close_price = float(row[6])
                        open_price = float(row[3])
                        change = close_price - open_price
                        
                        data[name]["price"] = close_price
                        data[name]["change"] = change
                    except (ValueError, IndexError):
                        data[name]["price"] = row[6]
                else:
                    logger.warning(f"Stooq returned unexpected row format for {sym}: {row}")
            else:
                logger.warning(f"Stooq returned status {response.status_code} for {sym}")
                
        except Exception as e:
            logger.error(f"Error fetching forex price for {name}: {e}")
            
    return data

def get_oil_prices():
    """
    Fetches WTI and Brent Crude Oil prices from Stooq.
    Returns a dictionary with 'WTI' and 'Brent' data (price, change).
    """
    data = {"WTI": {"price": None, "change": None}, "Brent": {"price": None, "change": None}}
    # CL.F = WTI Crude Oil, CB.F = Brent Crude Oil
    symbols = {"WTI": "CL.F", "Brent": "CB.F"}
    
    for name, sym in symbols.items():
        try:
            url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlc&h&e=csv"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                f = io.StringIO(response.text)
                reader = csv.reader(f)
                header = next(reader) # Skip header
                row = next(reader)    # Get data row
                
                if len(row) >= 7:
                    try:
                        close_price = float(row[6])
                        open_price = float(row[3])
                        change = close_price - open_price
                        
                        data[name]["price"] = close_price
                        data[name]["change"] = change
                    except (ValueError, IndexError):
                        data[name]["price"] = row[6]
                else:
                    logger.warning(f"Stooq returned unexpected row format for {sym}: {row}")
            else:
                logger.warning(f"Stooq returned status {response.status_code} for {sym}")
                
        except Exception as e:
            logger.error(f"Error fetching oil price for {name}: {e}")
            
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
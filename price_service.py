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

def format_price(price):
    if price is None:
        return "N/A"
    try:
        return f"${float(price):,.2f}"
    except (ValueError, TypeError):
        return "N/A"

def get_oil_prices():
    """
    Fetches WTI and Brent Crude Oil prices from Stooq.
    Returns a dictionary with 'WTI' and 'Brent' prices.
    """
    prices = {"WTI": None, "Brent": None}
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
                
                # Stooq CSV format: Symbol, Date, Time, Open, High, Low, Close
                # We want Close price. Usually index 6, but let's be safe if header changes?
                # Actually Stooq format is quite stable.
                if len(row) >= 7:
                    prices[name] = row[6] # Close price
                else:
                    logger.warning(f"Stooq returned unexpected row format for {sym}: {row}")
            else:
                logger.warning(f"Stooq returned status {response.status_code} for {sym}")
                
        except Exception as e:
            logger.error(f"Error fetching oil price for {name}: {e}")
            
    return prices

def get_prices():
    """
    Fetches current prices for BTC, ETH, TON, SOL, Gold (PAXG), Silver (KAG), and Oil.
    Returns a formatted string message.
    """
    # PAXG = Pax Gold (1 oz Gold backed token)
    # KAG = Kinesis Silver (1 oz Silver backed token)
    fsyms = "BTC,ETH,TON,SOL,PAXG,KAG"
    tsyms = "USD"
    url = f"{BASE_URL}?fsyms={fsyms}&tsyms={tsyms}&api_key={API_KEY}"
    
    crypto_prices = {}
    oil_prices = get_oil_prices()
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "RAW" in data:
            for symbol in ["BTC", "ETH", "TON", "SOL", "PAXG", "KAG"]:
                try:
                    crypto_prices[symbol] = data["RAW"][symbol]["USD"]["PRICE"]
                except KeyError:
                    crypto_prices[symbol] = None
        else:
            logger.error(f"Error fetching crypto data: {data}")

        # Construct the message
        message = (
            "📊 **Daily Market Update** 📊\n\n"
            "**Crypto:**\n"
            f"₿ **Bitcoin (BTC):** {format_price(crypto_prices.get('BTC'))}\n"
            f"💎 **Ethereum (ETH):** {format_price(crypto_prices.get('ETH'))}\n"
            f"💎 **Toncoin (TON):** {format_price(crypto_prices.get('TON'))}\n"
            f"☀️ **Solana (SOL):** {format_price(crypto_prices.get('SOL'))}\n\n"
            "**Metals (1 oz):**\n"
            f"🟡 **Gold (PAXG):** {format_price(crypto_prices.get('PAXG'))}\n"
            f"⚪ **Silver (KAG):** {format_price(crypto_prices.get('KAG'))}\n\n"
            "**Oil (Barrel):**\n"
            f"🛢️ **WTI Crude:** {format_price(oil_prices.get('WTI'))}\n"
            f"🛢️ **Brent Crude:** {format_price(oil_prices.get('Brent'))}\n"
        )
        
        return message

    except Exception as e:
        logger.error(f"Exception in get_prices: {e}")
        return "⚠️ An error occurred while fetching market data."

if __name__ == "__main__":
    # Test the function locally
    print(get_prices())
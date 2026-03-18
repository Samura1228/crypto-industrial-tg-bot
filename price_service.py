import os
import requests
import logging
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
    return f"${price:,.2f}"

def get_prices():
    """
    Fetches current prices for BTC, ETH, TON, SOL, Gold (PAXG), and Silver (KAG).
    Returns a formatted string message.
    """
    # PAXG = Pax Gold (1 oz Gold backed token)
    # KAG = Kinesis Silver (1 oz Silver backed token)
    fsyms = "BTC,ETH,TON,SOL,PAXG,KAG"
    tsyms = "USD"
    url = f"{BASE_URL}?fsyms={fsyms}&tsyms={tsyms}&api_key={API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "RAW" not in data:
            logger.error(f"Error fetching data: {data}")
            return "⚠️ Error fetching prices. Please try again later."

        prices = {}
        for symbol in ["BTC", "ETH", "TON", "SOL", "PAXG", "KAG"]:
            try:
                prices[symbol] = data["RAW"][symbol]["USD"]["PRICE"]
            except KeyError:
                prices[symbol] = None

        # Construct the message
        message = (
            "📊 **Daily Market Update** 📊\n\n"
            "**Crypto:**\n"
            f"₿ **Bitcoin (BTC):** {format_price(prices.get('BTC'))}\n"
            f"💎 **Ethereum (ETH):** {format_price(prices.get('ETH'))}\n"
            f"💎 **Toncoin (TON):** {format_price(prices.get('TON'))}\n"
            f"☀️ **Solana (SOL):** {format_price(prices.get('SOL'))}\n\n"
            "**Metals (1 oz):**\n"
            f"🟡 **Gold (PAXG):** {format_price(prices.get('PAXG'))}\n"
            f"⚪ **Silver (KAG):** {format_price(prices.get('KAG'))}\n"
        )
        
        return message

    except Exception as e:
        logger.error(f"Exception in get_prices: {e}")
        return "⚠️ An error occurred while fetching market data."

if __name__ == "__main__":
    # Test the function locally
    print(get_prices())
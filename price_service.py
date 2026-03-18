import os
import requests
import logging
import yfinance as yf
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

def get_crypto_prices():
    """Fetches crypto prices from CryptoCompare."""
    fsyms = "BTC,ETH,TON,SOL"
    tsyms = "USD"
    url = f"{BASE_URL}?fsyms={fsyms}&tsyms={tsyms}&api_key={API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "RAW" not in data:
            logger.error(f"Error fetching crypto data: {data}")
            return {}

        prices = {}
        for symbol in ["BTC", "ETH", "TON", "SOL"]:
            try:
                prices[symbol] = data["RAW"][symbol]["USD"]["PRICE"]
            except KeyError:
                prices[symbol] = None
        return prices
    except Exception as e:
        logger.error(f"Exception in get_crypto_prices: {e}")
        return {}

def get_metal_prices():
    """Fetches Gold and Silver prices from Yahoo Finance."""
    try:
        # GC=F is Gold Futures, SI=F is Silver Futures
        gold = yf.Ticker("GC=F")
        silver = yf.Ticker("SI=F")
        
        # Use history() to get the latest price, which is more reliable than .info
        gold_hist = gold.history(period="1d")
        silver_hist = silver.history(period="1d")
        
        if not gold_hist.empty:
            gold_price = gold_hist['Close'].iloc[-1]
        else:
            gold_price = None
            
        if not silver_hist.empty:
            silver_price = silver_hist['Close'].iloc[-1]
        else:
            silver_price = None
        
        return {
            "Gold": gold_price,
            "Silver": silver_price
        }
    except Exception as e:
        logger.error(f"Exception in get_metal_prices: {e}")
        return {"Gold": None, "Silver": None}

def format_price(price):
    if price is None:
        return "N/A"
    return f"${price:,.2f}"

def get_prices():
    """
    Fetches current prices for BTC, ETH, TON, SOL, Gold, and Silver.
    Returns a formatted string message.
    """
    crypto_prices = get_crypto_prices()
    metal_prices = get_metal_prices()
    
    # Construct the message
    message = (
        "📊 **Daily Market Update** 📊\n\n"
        "**Crypto:**\n"
        f"₿ **Bitcoin (BTC):** {format_price(crypto_prices.get('BTC'))}\n"
        f"💎 **Ethereum (ETH):** {format_price(crypto_prices.get('ETH'))}\n"
        f"💎 **Toncoin (TON):** {format_price(crypto_prices.get('TON'))}\n"
        f"☀️ **Solana (SOL):** {format_price(crypto_prices.get('SOL'))}\n\n"
        "**Metals:**\n"
        f"🟡 **Gold:** {format_price(metal_prices.get('Gold'))}\n"
        f"⚪ **Silver:** {format_price(metal_prices.get('Silver'))}\n"
    )
    
    return message

if __name__ == "__main__":
    # Test the function locally
    print(get_prices())
import ccxt
import time
import logging
import threading
import json
import os
import numpy as np
import requests
from app import app  # Import the Flask app

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Exchange API keys (replace with real keys)
BINANCE_API_KEY = "qzZG6H2yEkCDQDcL1TUG8leKoai1TvEjgFhl6g0eolixVHg1fmHIks3S7br4WpG3"
BINANCE_SECRET = "zaA21h1LaXhXSqV7oQJUuXLxNGlvQlfGWcvMPJmTvK41axgFuExbkFml50uKY5EK"

# Initialize exchange client
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET
})

# Trading pairs (USDT to USDC and USDT to DAI)
PAIRS = ["USDT/USDC", "USDT/DAI"]

# Ledger file
LEDGER_FILE = "trade_ledger.json"

def load_ledger():
    """Load trade ledger from a JSON file."""
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r") as file:
            return json.load(file)
    return {"trades": [], "average_profit": 0.0}  # If no ledger exists, create a fresh start

def save_ledger(ledger_data):
    """Save trade ledger to a JSON file."""
    with open(LEDGER_FILE, "w") as file:
        json.dump(ledger_data, file, indent=4)

def update_ledger(buy_price, sell_price, amount, pair):
    """Update the ledger with a new trade and calculate the running average profit."""
    ledger_data = load_ledger()
    profit = (sell_price - buy_price) * amount
    ledger_data["trades"].append({"pair": pair, "buy_price": buy_price, "sell_price": sell_price, "amount": amount, "profit": profit})
    
    total_profit = sum(trade["profit"] for trade in ledger_data["trades"])
    ledger_data["average_profit"] = total_profit / len(ledger_data["trades"])
    
    save_ledger(ledger_data)
    logging.info(f"Trade recorded: Pair: {pair}, Buy at {buy_price}, Sell at {sell_price}, Amount: {amount}, Profit: {profit}")
    logging.info(f"Running average profit: {ledger_data['average_profit']}")

def get_prices():
    """Fetches bid-ask prices from the exchange."""
    try:
        prices = {}
        for pair in PAIRS:
            ticker = binance.fetch_ticker(pair)
            prices[pair] = {
                "bid": ticker['bid'],
                "ask": ticker['ask'],
                "high": ticker['high'],
                "low": ticker['low']
            }
        return prices
    except Exception as e:
        logging.error(f"Error fetching prices: {e}")
        return None

def fetch_historical_data(pair, interval='1h', limit=100):
    """Fetch historical price data from Binance API."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={pair.replace('/', '')}&interval={interval}&limit={limit}"
        response = requests.get(url, timeout=0.5)
        data = response.json()
        return np.array([[float(candle[1]), float(candle[4])] for candle in data])  # Open and close prices
    except requests.exceptions.RequestException:
        return np.array([])

def predict_future_price(historical_data):
    """Predicts the future price using weighted averages based on historical data."""
    if historical_data.size == 0:
        return None
    
    weights = np.linspace(0.1, 1, len(historical_data))  # Increasing weights for recent data
    weighted_avg = np.average(historical_data[:, 1], weights=weights)
    return weighted_avg

def analyze_historical_data(pair):
    """Use a matrix-based approach to determine if arbitrage is historically profitable."""
    historical_data = fetch_historical_data(pair)
    if historical_data.size == 0:
        return False

    price_changes = np.diff(historical_data[:, 1])  # Calculate price changes
    covariance_matrix = np.cov(price_changes[:-1], price_changes[1:])  # Measure volatility correlation
    mean_return = np.mean(price_changes)
    risk = np.sqrt(np.var(price_changes))
    
    confidence_threshold = 1.5 * risk  # Define an arbitrage confidence threshold
    return mean_return > confidence_threshold

def execute_trade(amount, pair):
    """Executes buy and sell orders on Binance."""
    try:
        # Fetch daily high and low prices
        ticker = binance.fetch_ticker(pair)
        daily_high = ticker['high']
        daily_low = ticker['low']

        # Execute buy and sell orders in parallel
        buy_thread = threading.Thread(target=binance.create_market_buy_order, args=(pair, amount))
        sell_thread = threading.Thread(target=binance.create_market_sell_order, args=(pair, amount))
        
        buy_thread.start()
        sell_thread.start()
        
        buy_thread.join()
        sell_thread.join()
        
        buy_price = binance.fetch_ticker(pair)['ask']
        sell_price = binance.fetch_ticker(pair)['bid']
        
        # Check if the sell price is within the daily high and low range
        if sell_price < daily_low or sell_price > daily_high:
            logging.warning(f"Sell price {sell_price} is out of daily range ({daily_low} - {daily_high}). Trade aborted.")
            return
        
        update_ledger(buy_price, sell_price, amount, pair)
        
        logging.info(f"Executed trade on Binance for pair {pair}")
    except Exception as e:
        logging.error(f"Error executing trade: {e}")

def calculate_potential_profit(buy_price, sell_price, amount):
    """Calculate potential profit from a trade."""
    return (sell_price - buy_price) * amount

def convert_to_usdt():
    """Convert all balances to USDT if USDT balance is zero."""
    balance = binance.fetch_balance()
    usdt_balance = balance['total']['USDT']
    if usdt_balance == 0:
        for currency, amount in balance['total'].items():
            if currency != 'USDT' and amount > 0:
                pair = f"{currency}/USDT"
                try:
                    binance.create_market_sell_order(pair, amount)
                    logging.info(f"Converted {amount} {currency} to USDT")
                except Exception as e:
                    logging.error(f"Error converting {currency} to USDT: {e}")

def arbitrage():
    """Checks for arbitrage opportunities and executes trades."""
    while True:
        convert_to_usdt()  # Ensure we have USDT balance
        prices = get_prices()
        if prices:
            for pair in PAIRS:
                ask = prices[pair]["ask"]
                bid = prices[pair]["bid"]

                # Arbitrage condition
                if bid > ask:  # Buy and sell on Binance
                    balance = binance.fetch_balance()
                    usdt_balance = balance['total']['USDT']
                    amount = usdt_balance / 2  # Use 50% of the total USDT balance for each pair

                    # Ensure the amount does not exceed the available balance
                    if amount > usdt_balance:
                        logging.warning(f"Trade amount {amount} exceeds available USDT balance {usdt_balance}. Trade aborted.")
                        continue

                    historical_data = fetch_historical_data(pair.replace('/', ''))
                    predicted_price = predict_future_price(historical_data)
                    
                    if predicted_price and predicted_price > ask:  # Buy if predicted price is higher
                        if analyze_historical_data(pair.replace('/', '')):  # Use historical data validation
                            potential_profit = calculate_potential_profit(ask, bid, amount)
                            if potential_profit > 0:  # Ensure there is a profit to be made
                                logging.info(f"Arbitrage Opportunity: Pair: {pair}, Buy and Sell on Binance at {ask}, Potential Profit: {potential_profit}")
                                execute_trade(amount, pair)

        time.sleep(0.001)  # Short delay to avoid API rate limits

if __name__ == "__main__":
    # Start the Flask app in a separate thread
    threading.Thread(target=lambda: app.run(debug=True, use_reloader=False)).start()
    arbitrage()
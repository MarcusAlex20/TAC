from flask import Flask, jsonify, render_template
import json
import os

app = Flask(__name__, static_folder='static')

LEDGER_FILE = "trade_ledger.json"

def load_ledger():
    """Load trade ledger from a JSON file."""
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r") as file:
            return json.load(file)
    return {"trades": [], "average_profit": 0.0}  # If no ledger exists, create a fresh start

@app.route('/ledger')
def get_ledger():
    ledger_data = load_ledger()
    return jsonify(ledger_data)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    app.run(debug=True)

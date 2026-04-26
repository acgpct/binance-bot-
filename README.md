# Binance Spot EMA Bot

Day-trading bot for Binance Spot using an EMA crossover strategy. Built to run on **Binance testnet** first (fake money, real API).

## Setup

```bash
cd /Users/agneschan/Documents/00-Personal/Web/binance
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then get testnet API keys:
1. Go to https://testnet.binance.vision/
2. Log in with GitHub
3. Click "Generate HMAC_SHA256 Key" — save both the API Key and Secret Key
4. Paste them into `.env`

## Workflow

1. **Explore** — open `notebooks/explore.ipynb` in Jupyter, fetch data, look at charts.
2. **Backtest** — `python -m src.backtest` to simulate the strategy on historical data.
3. **Paper trade on testnet** — `python -m src.bot` to run live (testnet money).
4. **Go live (eventually)** — only after backtest + testnet show consistent profit. Set `BINANCE_LIVE=true` in `.env`.

## Strategy: EMA Crossover

- **Fast EMA** (default 9 periods) crosses **above** slow EMA (default 21) → BUY signal
- **Fast EMA** crosses **below** slow EMA → SELL signal
- Tunable in `src/strategy.py`

## Project layout

```
src/
├── exchange.py    # Binance connection (testnet toggle)
├── data.py        # fetch & cache OHLCV
├── strategy.py    # EMA crossover signals
├── backtest.py    # simulate on history
└── bot.py         # live trading loop
notebooks/
└── explore.ipynb  # interactive research
data/              # cached OHLCV (gitignored)
```

## Safety rules

- `BINANCE_LIVE` defaults to `false` (testnet). Flipping it is the only way to touch real funds.
- The bot logs every order before placing it. Read the logs.
- Start with one symbol (BTC/USDT), small size, one position at a time.

# 🤖 Binance Rotational Momentum Bot

A systematic crypto trading bot that scans Binance Spot, ranks USDT pairs by
momentum each day, and rotates capital into the top 5. Includes a live
Streamlit dashboard, multi-coin scanner, and a comprehensive backtesting suite.

> **⚠️ Risk warning.** Crypto trading is extremely risky. The strategy in this
> repo has historically experienced **drawdowns of 50–65%** in backtests, and
> backtests overstate live performance. Run on Binance testnet first — for at
> least a month — and only trade real money you can afford to lose entirely.
> This is a personal research project, not financial advice.

---

## What it does

Imagine you can bet on 25 horses but only pick 5 at a time. Every 24 hours:

1. Look at the **top 25 USDT pairs on Binance** by 24h volume
2. Score each by **momentum** (% return over the last ~10 days) and **trend health** (price above 50-period EMA, short EMA above long EMA)
3. Hold the **top 5** by momentum, equal-weighted
4. **Rotate** out of any holding that fell out of the top 5; buy any new entrants

That's the whole strategy. The premise: in crypto, when something starts running, it often keeps running for weeks. Catching even one such run pays for many losing trades. The strategy accepts ugly weeks (and the occasional brutal month) in exchange for the asymmetric upside of capturing those runs.

---

## Architecture

```
src/
├── exchange.py            # Binance connection — testnet for trading, public mainnet for data
├── data.py                # OHLCV fetching + parquet cache
├── scanner.py             # rank top USDT pairs by momentum + trend filter
├── strategy.py            # legacy single-coin EMA crossover (with HTF filter + SL/TP)
├── backtest.py            # backtest the EMA strategy
├── rotation_backtest.py   # backtest the rotational momentum strategy
├── rotation_bot.py        # LIVE rotational bot (testnet by default)
├── bot.py                 # legacy single-coin EMA bot
└── stress_test.py         # parameter robustness + walk-forward + fee sensitivity tests
dashboard/
└── app.py                 # Streamlit dashboard with live P&L, equity curve, scanner picks
notebooks/
└── explore.ipynb          # interactive research
data/                      # cached OHLCV + runtime state (gitignored)
```

The two-exchange split is deliberate: **mainnet (public)** is used for scanning
and historical data (testnet only retains ~25 days of 5m candles), while
**testnet (authenticated)** is used for actual order execution. The bot reads
"what's pumping in the real world" but executes against fake money until you
flip `BINANCE_LIVE=true`.

---

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/acgpct/binance-bot-.git
cd binance-bot-
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get testnet API keys

1. Go to https://testnet.binance.vision/
2. Log in with GitHub
3. Click **Generate HMAC_SHA256 Key** — save the API Key and Secret Key
4. Copy `.env.example` to `.env` and paste the keys

```bash
cp .env.example .env
# Edit .env, paste your keys
```

### 3. Run the bot

```bash
# One rebalance cycle, no orders (sanity check)
python -m src.rotation_bot --show-picks

# Run continuously on testnet (recommended for first 30 days)
caffeinate -i python -m src.rotation_bot
```

### 4. Open the dashboard

In a separate terminal:

```bash
streamlit run dashboard/app.py
# Opens at http://localhost:8501
```

The dashboard shows current P&L (big number, hard to miss), equity curve vs
BTC HODL benchmark, per-coin holdings, and what the scanner would pick right
now.

---

## Backtests

The project ships with three backtest scripts:

| Script | What it does |
|---|---|
| `python -m src.backtest` | Single-coin EMA crossover backtest |
| `python -m src.rotation_backtest` | Rotational momentum portfolio backtest |
| `python -m src.stress_test` | Robustness sweep + walk-forward + fee sensitivity |

### Backtest results: biased vs bias-aware (1y of 4h data)

The naive backtest uses *today's* top-25 USDT pairs as the universe across the
entire historical period — which **silently selects coins that turned out to
be popular**, dramatically inflating returns. This repo includes a
`--bias-aware` flag that fixes this: at each rebalance, it ranks coins by
their *trailing 30-day USD volume at that point in time* from a 100-coin
candidate pool, mimicking what a live scanner would have actually seen.

| Configuration | 1y return | Max DD | What it tests |
|---|---|---|---|
| **A. Biased** — fixed top-25 (legacy) | **+145%** | -55% | Inflated by hindsight |
| **B. Bias-aware** — dynamic top-25 of 100 | **−86%** | -90% | Tight universe with no hindsight |
| **C. Bias-aware** — dynamic top-50 of 100 | -71% | -89% | — |
| **E. Bias-aware** — dynamic top-5 of 100 | **+96%** | -68% | Broad scan, point-in-time |
| BTC buy-and-hold | -17% | — | Benchmark |

**Reading the table honestly:**

- The biased +145% **vanishes** when you use a tight bias-aware universe (B/C/D)
- The strategy **only works** when scanning a wide candidate pool (E: top-5 of 100, +96%)
- This is consistent with how the live bot operates (it scans top-25 from *all* current Binance pairs, not a fixed list)
- Realistic real-world expectation: **somewhere between -50% and +50% per year**, with **50–70% drawdowns** the norm

The takeaway: **the strategy probably has a small real edge over buy-and-hold,
but not the eye-popping numbers from the naive backtest.** Anyone showing you
a crypto strategy with +200%+ backtest returns and not discussing universe
construction is either ignorant or selling something. Be skeptical.

Run the comparison yourself:
```bash
# Naive (biased)
python -m src.rotation_backtest --top 25 --days 365

# Bias-aware
python -m src.rotation_backtest --bias-aware --candidate-pool 100 --universe-size 25 --days 365
```

---

## Honest performance discussion

Two days of testnet running (April 2026) produced this sequence:

- Day 1 (deploy): bought 5 coins at top of their pumps
- Day 2 morning: -10% (ORCA dropped 29% from entry)
- Day 2 evening: rebalanced, dropped some losers
- Day 3 morning: +1.8% (ZBT pumped 27%, LUNC 15%)

This is **textbook behavior** for a momentum strategy: nausea on the daily
chart, healthy upward drift on the weekly chart. If you can't watch -10% days
without panicking, **reduce position size or use a different strategy**.

---

## Configuration knobs

The bot has sensible defaults from the stress test (best risk-adjusted config),
but everything is tunable:

```bash
python -m src.rotation_bot \
  --top-k 5 \              # number of coins to hold
  --universe 25 \          # universe size (top N USDT pairs by volume)
  --timeframe 4h \         # bar size for momentum scoring
  --momentum-lookback 60 \ # bars used for momentum % return (60 × 4h ≈ 10 days)
  --rebalance-bars 6       # rebalance every N bars (6 on 4h = daily)
```

Other useful flags:

- `--dry-run` — log decisions but place no orders
- `--show-picks` — print current picks and exit
- `--once` — run a single rebalance cycle then exit

### Going live (eventually)

After **at least 30 days** of testnet running where the live results track
backtest expectations:

1. Get **real** Binance API keys (not testnet)
2. Set `BINANCE_LIVE=true` in `.env`
3. Restart the bot

You'll get a 5-second warning before any live order. The bot will be more
careful about minimum order sizes and will refuse to deploy below ~$6 per
position.

**Don't go live before you can sit through a -30% drawdown without touching
anything.** That's the actual test of whether you should run this with money.

---

## Roadmap

- [x] **Fix survivorship bias in backtests** — point-in-time universe via `--bias-aware`
- [ ] Add bull/bear regime filter (only trade when BTC is uptrending)
- [ ] Include delisted coins in candidate pool (truly bias-free backtest)
- [ ] Multi-lookback momentum (combine 20/40/60-bar ranks for robustness)
- [ ] Walk-forward parameter optimization
- [ ] VPS deployment guide (systemd service)
- [ ] Telegram/email alerts on rebalance and big drawdowns
- [ ] SQLite for state instead of JSON

---

## Safety rules

1. **`BINANCE_LIVE=false` by default.** Flipping it is the only way to touch real money.
2. **`.env` is gitignored.** Never commit keys.
3. **The repo is private.** Keep it that way — public repos with `BINANCE_API_KEY=` patterns get scraped within minutes.
4. **The bot only manages what it bought.** Pre-existing testnet balances are ignored, so the bot won't touch coins you put there manually.
5. **Position state persists.** Restarting the bot mid-position picks up where it left off; deleting `data/rotation_state.json` resets the bot's view (positions on the exchange remain).

---

## Project status

Personal research project. Not maintained for production use. Use at your own
risk. If this is useful to you, fork it. If you find a bug, open an issue.

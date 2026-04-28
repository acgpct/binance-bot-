# 💰 DCA bot — stocks/ETFs

A second bot that runs alongside the crypto rotation bot. Auto-buys a fixed
amount of an ETF every Friday with an optional **tactical multiplier**:
buys more when the market is down, less when it's pumping.

```
                ┌──────────────────────────────────┐
                │  Schedule: every Fri 16:00 local │
                │  (launchd on Mac)                │
                └──────────────┬───────────────────┘
                               ▼
                ┌──────────────────────────────────┐
                │  src/dca_bot.py                  │
                │  1. Read S&P 500 trailing-week % │  ◀── yfinance
                │  2. Compute tactical multiplier  │
                │  3. Place market BUY:            │
                │     base × multiplier USD        │
                │  4. Append to dca_history.csv    │
                │  5. Notify (osascript)           │
                └──────────────┬───────────────────┘
                               │
                ┌──────────────▼───────────────────┐
                │  Three modes:                    │
                │   simulation  ← yfinance only    │
                │   paper       ← IBKR paper acc   │
                │   live        ← IBKR real money  │
                └──────────────────────────────────┘
```

## Three execution modes

| Mode | Broker connection | Money used | What you need |
|---|---|---|---|
| `simulation` ⭐ | None | None (logged only) | Just `pip install -r requirements.txt` |
| `paper` | IBKR paper-trading account | Fake money on IBKR | An IBKR account + IB Gateway running |
| `live` | IBKR live | **Real money** | An IBKR account, IB Gateway, and a strong stomach |

**Start in `simulation` mode.** It uses yfinance to "buy" at real market
prices and logs every trade. You can validate the strategy + scheduling
for weeks before risking any money.

## The tactical multiplier

Pure DCA is great. The tactical version is slightly better, with
empirical support: **buy more when the market is down**.

Each cycle, the bot computes the S&P 500's trailing 5-trading-day return
and applies a multiplier:

| Last week's S&P move | Multiplier | Reason |
|---|---|---|
| ≤ −7% | **2.0x** | Big drop — double the allocation |
| ≤ −3% | 1.5x | Moderate drop — buy 50% more |
| −3% to +3% | 1.0x | Normal week — base allocation |
| +3% to +7% | 0.7x | Rally — slow down |
| > +7% | 0.5x | Big pump — half allocation, save cash for the dip |

The multipliers are deliberately **gentle** (max 2.0x, min 0.5x). Aggressive
"buy the dip" strategies feel great but underperform on average — most
"dips" aren't actually buying opportunities.

Disable it with `--no-tactical` for pure boring DCA.

## Quick start (simulation mode)

```bash
# From the project directory
.venv/bin/python -m src.dca_bot --dry-run         # preview, no logging
.venv/bin/python -m src.dca_bot --ticker VT       # simulate buying VT
cat data/dca_history.csv                          # see what was logged
```

Open the dashboard — a **DCA bot** section appears at the bottom showing:

- Total invested · current value · DCA P&L
- Per-ticker breakdown with average cost, current price, P&L %
- Recent buys with the multiplier and S&P weekly move

## Schedule it (macOS launchd)

```bash
bash tools/install_dca_schedule.sh
```

Installs a launchd agent that fires **every Friday at 16:00 local time**.
The wrapper runs the bot, appends to the log, and posts a desktop
notification.

Test it now without waiting for Friday:
```bash
bash tools/run_dca.sh
```

To uninstall:
```bash
bash tools/uninstall_dca_schedule.sh
```

## Switching to real money (when ready)

Once your IBKR account is approved and funded, follow these steps in order:

### 1. Open an Interactive Brokers account

Go to https://www.interactivebrokers.com → Open Account.
- Approval takes 3–5 days
- Wire some funds (CHF/EUR/USD)
- IBKR is one of the cheapest/best brokers — used by professionals

### 2. Install IB Gateway

The "headless" version of IBKR's TWS desktop app. Lighter, just runs the
API. https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

After installing, log in with your IBKR credentials and choose:
- **Paper Trading** mode → port `7497` (recommended for first runs)
- **Live** mode → port `7496` (real money)

Keep IB Gateway running while the DCA bot fires. You can either:
- Run it on your Mac (open it Friday afternoons before the bot fires)
- Run it on your VPS as a service (more reliable but more setup)

### 3. Configure the bot for paper trading first

Add these lines to your `.env`:

```
DCA_MODE=paper
DCA_TICKER=VT             # or VWCE.AS, or any ETF
DCA_BASE_AMOUNT=500
DCA_CURRENCY=USD          # or EUR, CHF
DCA_EXCHANGE=SMART        # SMART = let IBKR route; AEB for Amsterdam, NYSE for US
IBKR_PORT=7497            # paper trading
IBKR_CLIENT_ID=2
```

Run a manual test:
```bash
.venv/bin/python -m src.dca_bot --mode paper
```

Verify in IBKR's portfolio view that the trade actually happened.

### 4. Flip to live (only after weeks of paper trading)

Edit `.env`:
```
DCA_MODE=live
IBKR_PORT=7496        # live port
```

Or pass `--mode live` on the command line. The bot prints a 5-second
warning before placing a real-money order.

## Common ETFs

| Ticker | What it is | Currency | Where |
|---|---|---|---|
| **VT** | Vanguard Total World | USD | NYSE — global diversification, US tax law |
| **VTI** | Vanguard Total US Market | USD | NYSE — US-only |
| **VWCE.AS** | Vanguard FTSE All-World UCITS (accumulating) | EUR | Amsterdam — best for EU/Swiss investors |
| **VWRL.AS** | Same, distributing (pays dividends) | EUR | Amsterdam |
| **CHSPI.SW** | iShares Core SMI | CHF | Switzerland — domestic equity |
| **AGGH.SW** | iShares Global AAA-AA Bonds | CHF | Switzerland — defensive |

A common Swiss-friendly portfolio: **70% VWCE + 20% CHSPI + 10% AGGH**, DCA'd weekly or monthly.

## Costs and gotchas

- **IBKR commissions**: ~$1 per trade for European ETFs. Buying weekly =
  ~$52/yr. Switch to monthly (`Day=1` and `Hour=16` in the plist) to cut
  this 4x with negligible impact on returns.
- **FX conversion**: if you fund in CHF and buy a USD ETF, IBKR converts
  at ~spot. Spread is small (< 0.01%) but real.
- **Settlement**: T+2. Cash isn't truly available until 2 business days
  after a sell.
- **Wealth tax (Switzerland)**: ETF holdings count toward your annual
  wealth tax. Capital gains are not taxed for individuals.
- **Dividend tax (Switzerland)**: Distributing ETFs pay dividends that
  count as income tax. Accumulating ETFs (VWCE) avoid this — slightly
  more tax-efficient.

## Why this is better than just "use IBKR's recurring purchase feature"

You don't need to use this bot. IBKR has built-in periodic investment.
That said, this bot gives you:

1. **The tactical multiplier** — IBKR's feature buys a fixed amount; this
   bot buys more on red weeks, less on green. Small but real edge.
2. **All your data in one dashboard** — same Streamlit app shows crypto +
   DCA together
3. **Logs everything** — you can backtest your own DCA history later
4. **Open source** — modify the multiplier, the schedule, the universe

If none of that matters to you, **just use IBKR's recurring purchase**.
It's set-and-forget, no code, no IB Gateway, no scheduling. Honest answer.

## Troubleshooting

### "could not connect to IB Gateway at 127.0.0.1:7497"

IB Gateway isn't running. Open it, log in, and confirm the API port
matches what you set (`IBKR_PORT` in `.env`).

### Bought 0 shares

Two common causes:
- **Order amount < 1 share at market price** — your `--amount` is too small.
  Increase it or pick a cheaper ETF.
- **Min notional** — some exchanges have minimum order sizes. Bump amount.

### "could not get a market price for VWCE.AS"

The ticker symbol is wrong for IBKR. Try the variants:
- `VWCE` with `exchange=AEB` and `currency=EUR`
- `VT` with `exchange=ARCA` and `currency=USD`

IBKR's contract resolver is finicky. Check
[IBKR's contract search](https://www.interactivebrokers.com/en/trading/products-stocks.php)
for the canonical symbol.

### Tactical multiplier always returns 1.0

The benchmark fetch (yfinance for SPY) is failing. The bot falls back to
1.0 if it can't get data. Check your internet connection or try
`--no-tactical` for pure DCA.

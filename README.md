# 🤖 Binance Rotational Momentum Bot

A systematic crypto trading bot for Binance Spot. Every 24 hours it scans the
top 25 USDT pairs by volume, ranks them by momentum, and rotates capital into
the top 5. Runs unattended on a $4/month VPS with a local Streamlit dashboard.

> **⚠️ Risk warning.** Crypto trading is extremely risky. Backtests of this
> strategy show drawdowns of 50–65%, and backtests overstate real performance.
> Run on Binance testnet for at least a month before considering live money.
> Personal research project, not financial advice.

---

## Table of contents

- [The strategy in plain English](#the-strategy-in-plain-english)
- [Architecture overview](#architecture-overview)
- [How the strategy actually works](#how-the-strategy-actually-works)
- [The bot's lifecycle](#the-bots-lifecycle)
- [The dashboard](#the-dashboard)
- [State management & self-healing](#state-management--self-healing)
- [Backtesting suite](#backtesting-suite)
- [Quick start (local Mac)](#quick-start-local-mac)
- [Deploying to a VPS](#deploying-to-a-vps)
- [Operations & monitoring](#operations--monitoring)
- [Failure modes the bot handles](#failure-modes-the-bot-handles)
- [Configuration knobs](#configuration-knobs)
- [Going live (eventually)](#going-live-eventually)
- [Roadmap](#roadmap)
- [Safety rules](#safety-rules)

---

## The strategy in plain English

Imagine you can bet on 25 horses but only pick 5 at a time. Every 24 hours:

1. Look at the **top 25 USDT pairs on Binance** by 24-hour volume
2. Score each by **momentum** (% price return over the last ~10 days) and
   **trend health** (price above its 50-period EMA, short EMA above long EMA)
3. Hold the **top 5** by momentum, equal-weighted
4. **Rotate** out of any holding that fell out of the top 5; buy any new
   entrants

That's it. The premise: in crypto, when something starts running it tends to
keep running for weeks. Catching even one such run pays for many losing
trades. The strategy accepts ugly weeks (and the occasional brutal month) in
exchange for the asymmetric upside of capturing those runs.

---

## Architecture overview

```
                                 ┌──────────────────────────────────┐
                                 │      Binance Spot Mainnet        │
                                 │  (public API, no auth needed)    │
                                 └─────────────┬────────────────────┘
                                               │
                                               │ universe + OHLCV (scanning)
                                               │
   ┌──────────────────────────────────┐        │
   │      Binance Spot Testnet        │        │
   │  (authenticated trading account) │◀───────┼─── orders + balances
   └────────────────┬─────────────────┘        │
                    │                          │
                    │   ┌──────────────────────┴───────────────────┐
                    │   │              VPS (DigitalOcean)          │
                    │   │  ┌─────────────────────────────────────┐ │
                    │   │  │  rotation_bot.py (systemd service)  │ │
                    │   │  │  • scanner.py (mainnet)             │ │
                    │   └──┤  • exchange.py (testnet for trades) │ │
                    │      │  • strategy: top-5 by momentum      │ │
                    │      │  • state: data/rotation_state.json  │ │
                    │      │  • equity: data/equity_history.csv  │ │
                    │      └─────────────────────────────────────┘ │
                    │                                              │
                    │      ┌──────────────────────────────────────┐│
                    │      │  systemd auto-restart, journald logs ││
                    │      └──────────────────────────────────────┘│
                    │                                              │
                    │       scp pulls state.json + equity.csv      │
                    └─────────▶ ┌──────────────────────────────────┴┐
                                │           Local Mac               │
                                │  ┌──────────────────────────────┐ │
                                │  │  Streamlit dashboard         │ │
                                │  │  (dashboard/app.py)          │ │
                                │  │  • reads state from sync     │ │
                                │  │  • queries testnet directly  │ │
                                │  │    for current prices/bal    │ │
                                │  └──────────────────────────────┘ │
                                └───────────────────────────────────┘
```

**Two exchanges, deliberately.** The bot uses two `ccxt.binance` clients:

- **`get_data_exchange()`** — public mainnet, no auth. Used for scanning the
  universe and fetching historical OHLCV. The testnet only retains ~25 days
  of intraday data and a small subset of pairs, so backtesting and scanning
  must use real market data.
- **`get_exchange()`** — authenticated client; testnet by default,
  flips to mainnet when `BINANCE_LIVE=true`. Used only for placing orders
  and reading account balances.

The bot reads "what's pumping in the real world" but executes against fake
money until you flip the env var.

---

## How the strategy actually works

### Step 1: build the universe

`scanner.get_universe()` calls Binance mainnet's `fetchTickers`, filters to
`*/USDT` pairs, removes:
- Stablecoins (USDC, FDUSD, TUSD, BUSD, DAI, USDP, EUR, GBP, etc.)
- Leveraged tokens (anything ending in UP/DOWN/BULL/BEAR)
- Pairs with 24h quote volume below the threshold (default $5M)

Sorts by 24h quote volume descending, takes the top N (default 25).

### Step 2: score each coin

For each coin in the universe, fetch ~14 days of 4h candles from mainnet and
compute (`scanner.score()`):

```
ema_short  = EMA(close, 20)
ema_long   = EMA(close, 50)
ATR%       = mean(true_range, 14) / close × 100        # volatility proxy

in_uptrend       = (close > ema_long) AND (ema_short > ema_long)
above_long_pct   = (close / ema_long - 1) × 100
momentum_pct     = (close / close[-momentum_lookback] - 1) × 100
```

Where `momentum_lookback` defaults to 60 bars (≈ 10 days on 4h).

**Filter**: only coins with `in_uptrend == True` are eligible.
**Rank**: sort eligible coins by `momentum_pct` descending.

### Step 3: pick top K

`rotation_bot.pick_targets()` takes the top K (default 5) and intersects them
with what's tradeable on the configured exchange (testnet supports ~2,180
USDT pairs out of the ~500 mainnet ones we'd consider — most overlap, but a
handful don't). Picks not tradeable on the configured exchange are skipped.

### Step 4: rebalance

For every coin in the new picks list:

- Already held & still in picks → keep, no action
- Held & no longer in picks → SELL (market order)
- New pick & not held → BUY (market order, allocate equal share of free cash)

Every 24h, repeat.

---

## The bot's lifecycle

`python -m src.rotation_bot` runs an infinite loop. Each iteration is one
**rebalance cycle**:

```
START
  │
  ├── Connect to mainnet (data) and testnet/live (trading)
  ├── Load state from data/rotation_state.json
  └── Log mode (TESTNET / LIVE)
  │
  ▼
LOOP {
  │
  ├── reconcile_state_with_exchange()    [SELF-HEAL]
  │     For each tracked symbol:
  │       actual = exchange.fetch_balance()[base].free
  │       if actual <= 0: drop from state
  │       else: state.units = actual
  │
  ├── pick_targets()
  │     Universe scan → score → rank → top K → filter to tradeable
  │
  ├── For each holding NOT in picks:
  │     market_sell(symbol, units)        [uses min(state, actual)]
  │
  ├── For each pick NOT yet held:
  │     market_buy_quote(symbol, cash_per_pick)
  │
  ├── log_equity_snapshot()
  │     Append { timestamp, equity, cash, btc_price, holdings } to
  │     data/equity_history.csv
  │
  ├── save_state(state)
  │     Persist updated holdings + last_rebalance to JSON
  │
  └── time.sleep(86400)  ≈ 24h on a 4h timeframe with 6-bar interval
}
```

**Failure handling**: the outer try/except catches all exceptions, logs the
traceback, and sleeps 60s before retrying. SIGTERM / Ctrl+C is caught
cleanly and the loop exits without leaving the state in a half-written
state.

**Restart safety**: if the process dies and restarts (systemd's
`Restart=on-failure`), the state file is loaded from disk and the bot
resumes where it left off. The reconcile step at the start of every cycle
ensures the in-memory state matches what's actually on the exchange.

---

## The dashboard

📖 **Full dashboard guide: [`dashboard/DASHBOARD.md`](dashboard/DASHBOARD.md)** — covers every section, what to look for, sidebar controls, and troubleshooting.

Quick overview: `dashboard/app.py` (Streamlit) shows:

| Section | What it shows | Where the data comes from |
|---|---|---|
| **Topbar** | Mode (testnet/live), bot status pill, last rebalance time | `data/rotation_state.json` + clock |
| **Hero card** | Money put in, current value, profit/loss in $ and % | starting cash (sidebar) + live exchange balance |
| **Secondary tiles** | vs BTC HODL %, cash USDT, position count, BTC price | `equity_history.csv` (start point) + live ticker |
| **Equity chart** | Strategy equity over time + BTC HODL benchmark | `equity_history.csv` (snapshots) |
| **Portfolio donut** | Allocation % across positions + cash | live ticker × `state.units` |
| **Holdings table** | Per-coin entry/current/P&L%/P&L$/value/weight | state + live ticker |
| **Live scanner** | What the bot would pick *right now* | mainnet API (fresh scan, ~10s) |
| **Recent rebalances** | Last 20 rebalance snapshots | `equity_history.csv` |

### Where the dashboard runs

The dashboard runs **on your Mac** (or wherever you want), not on the VPS.
Two reasons:

1. **You don't want to expose Streamlit publicly** (it has no auth)
2. **The dashboard mostly queries Binance directly** (current balance, prices,
   tickers), so it works the same regardless of where the bot lives

The two state files (`rotation_state.json`, `equity_history.csv`) are the
exception — they're written by the bot, read by the dashboard. When the bot
runs on a VPS, you sync them to your Mac with:

```bash
bash deploy/sync_from_vps.sh <VPS-IP>
```

This `scp`s the two files down. Run before opening the dashboard for fresh
data.

---

## State management & self-healing

The bot persists two things:

### `data/rotation_state.json`

```json
{
  "holdings": {
    "ZBT/USDT": {
      "units": 17044.6,
      "entry_price": 0.21744,
      "entered_at": "2026-04-28T10:08:50+00:00"
    },
    "ORCA/USDT": { ... }
  },
  "last_rebalance": "2026-04-28T10:08:50+00:00"
}
```

What it tracks: which symbols the bot is currently managing, how many units
of each, the price the bot bought at, and when the last rebalance happened.

### `data/equity_history.csv`

```csv
timestamp,equity,cash,btc_price,n_positions,holdings
2026-04-27T06:22:37+00:00,9297.65,19.34,77859.56,5,ORCA/USDT|ZBT/USDT|D/USDT|LUNC/USDT|PENGU/USDT
2026-04-28T10:08:50+00:00,8782.96,226.19,78145.20,5,ORCA/USDT|ZBT/USDT|LUNC/USDT|PENGU/USDT|APE/USDT
```

What it tracks: a snapshot of equity, cash, BTC price, and held symbols at
each rebalance. Used by the dashboard for the equity chart and the BTC HODL
benchmark.

### Self-healing reconciliation

A class of bugs we hit early on: **state file drifts from reality**. Causes:

- Testnet quirks: a buy of 132,401 D was capped at the testnet's seed
  balance of 18,446
- Partial fills on illiquid pairs
- The bot restarting on a different machine inheriting an empty state file
  while the exchange account already had positions
- Fee deductions or rounding

To prevent any of these from corrupting the bot's behaviour,
`reconcile_state_with_exchange()` runs at the **start of every rebalance**:

```python
for sym in state['holdings']:
    actual_free = exchange.fetch_balance()[sym.base].free
    if actual_free <= 0:
        drop the symbol from state
    else:
        state[sym].units = actual_free   # trust the exchange
```

After this, the bot's view always matches reality. The defensive
`market_sell()` also caps the sell quantity at `min(state.units,
actual_free)` as a second line of defence.

**What it does NOT do**: auto-adopt symbols that aren't already in state.
The bot only manages what it has explicitly bought. This keeps it from
trying to "manage" the testnet's seeded balances of 200+ random altcoins.

---

## Backtesting suite

Three backtest scripts, in increasing order of intellectual honesty:

| Script | What it tests | Honesty level |
|---|---|---|
| `python -m src.backtest` | Single-coin EMA crossover (legacy) | Naive |
| `python -m src.rotation_backtest` | Top-K rotation, fixed universe | Naive (survivorship-biased) |
| `python -m src.rotation_backtest --bias-aware` | Top-K rotation, point-in-time universe | Honest |
| `python -m src.stress_test` | Robustness sweep + walk-forward + fee sensitivity | Honest |

### Naive vs bias-aware

The naive backtest uses *today's* top-25 USDT pairs as the universe across
the entire historical period — silently selecting coins that turned out to
be popular, dramatically inflating returns.

The bias-aware backtest fixes this: at each rebalance, it ranks coins by
*trailing 30-day USD volume at that point in time* from a 100-coin
candidate pool, mimicking what a live scanner would have actually seen.

| Configuration | 1y return | Max DD | What it tests |
|---|---|---|---|
| **A. Biased** — fixed top-25 (legacy) | **+145%** | -55% | Inflated by hindsight |
| **B. Bias-aware** — dynamic top-25 of 100 | **−86%** | -90% | Tight universe, no hindsight |
| **C. Bias-aware** — dynamic top-50 of 100 | -71% | -89% | — |
| **E. Bias-aware** — dynamic top-5 of 100 | **+96%** | -68% | Broad scan, point-in-time |
| BTC buy-and-hold (benchmark) | -17% | — | — |

Realistic real-world expectation: somewhere between **−50% and +50% per
year** with **50–70% drawdowns** the norm. The strategy probably has a
small real edge over BTC, but not the +200% the naive backtest implied.

Run the comparison yourself:

```bash
python -m src.rotation_backtest --top 25 --days 365                                    # naive
python -m src.rotation_backtest --bias-aware --candidate-pool 100 --universe-size 25 --days 365   # honest
```

### Stress test

`python -m src.stress_test` runs three tests on 1y of 4h data:

1. **Robustness sweep** — 60 configurations of (top_k, momentum_lookback,
   rebalance frequency) to see if good results are clustered (real edge) or
   isolated (overfit)
2. **Walk-forward** — runs the best config on 10 overlapping 90-day windows;
   reports the distribution of returns and worst-window
3. **Fee sensitivity** — same config at fees of 0.05% / 0.1% / 0.2% / 0.5%

---

## Quick start (local Mac)

### Install

```bash
git clone https://github.com/acgpct/binance-bot-.git
cd binance-bot-
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Get testnet API keys

1. Visit https://testnet.binance.vision/ → log in with GitHub
2. Click **Generate HMAC_SHA256 Key** → save both keys
3. Copy `.env.example` to `.env` and paste them in

```bash
cp .env.example .env
# edit .env, paste your testnet keys
```

### First run

```bash
# Sanity check — what would the bot pick? (no orders)
python -m src.rotation_bot --show-picks

# Dry-run a full cycle — log everything but place no orders
python -m src.rotation_bot --dry-run --once

# Run continuously (Ctrl+C to stop)
caffeinate -i python -m src.rotation_bot
```

`caffeinate -i` stops macOS from sleeping the bot when you close the lid.
The bot rebalances every 24h.

### Open the dashboard (separate terminal)

```bash
streamlit run dashboard/app.py
# opens at http://localhost:8501
```

---

## Deploying to a VPS

The bot needs to run continuously, which means either:
- Your Mac is always awake and plugged in, or
- It runs on a server somewhere

For the second, see the dedicated deployment guide:

👉 **[`deploy/DEPLOY.md`](deploy/DEPLOY.md)** — step-by-step DigitalOcean / Hetzner setup

End-to-end: ~15 minutes. Cost: $4–6/month. The repo includes:

- `deploy/setup.sh` — one-shot Ubuntu 24.04 provisioning script
- `deploy/binance-bot.service` — `systemd` service definition with
  auto-restart, journald logging, and basic process hardening
- `deploy/sync_from_vps.sh` — pulls the bot's state files down to your Mac
  so the dashboard shows live data

---

## Operations & monitoring

### Bot status (on VPS)

```bash
ssh root@<VPS-IP>
systemctl status binance-bot                         # is it running?
journalctl -u binance-bot -f                         # live logs
journalctl -u binance-bot -n 100 --no-pager          # last 100 lines
journalctl -u binance-bot --since "1 hour ago"       # last hour
```

### Sync state to your Mac dashboard

```bash
# In the project directory on your Mac
bash deploy/sync_from_vps.sh <VPS-IP>
# Then refresh the dashboard tab
```

### Set-and-forget automation (recommended)

Two scripts that remove the need to ever open a terminal again:

**Auto-sync** — Mac launchd job pulls VPS state every 30 min. Dashboard always fresh, no manual `sync_from_vps.sh`:

```bash
# On your Mac. Requires passwordless SSH key set up (ssh-copy-id root@<vps-ip>)
bash tools/install_auto_sync.sh
```

**Auto-heal** — VPS-side hourly cron that restarts the bot if `last_rebalance` is older than 26h. Replaces the manual "bot is Late → SSH → restart" routine:

```bash
# On the VPS as root, after `git pull`
bash /home/botuser/binance-bot-/deploy/install_auto_heal.sh
```

After both are installed: the bot self-heals if it gets stuck, the dashboard auto-refreshes from VPS, and you only need to touch the terminal again if something is genuinely wrong.

### Weekly summary notification (macOS)

Get a desktop notification every Sunday at 18:00 with your weekly P&L,
week-over-week change, vs-BTC edge, holdings, best/worst coin, and any
drawdown alerts — all without opening the dashboard.

Install once:

```bash
bash tools/install_weekly_notification.sh
# enter your VPS IP if prompted (optional, for auto-sync)
```

Test it now (instead of waiting for Sunday):

```bash
bash tools/run_weekly_summary.sh
# A macOS notification should appear within a few seconds.
```

The full report is saved to `data/weekly_reports/<date>.txt` and appended
to `data/weekly_reports/all_reports.log` so you have a running history.

Uninstall:

```bash
bash tools/uninstall_weekly_notification.sh
```

How it works: a `launchd` agent (`~/Library/LaunchAgents/com.user.binance-bot.weekly-summary.plist`)
calls `tools/run_weekly_summary.sh` on the schedule. The wrapper optionally
syncs from VPS first (if you set up passwordless SSH), runs
`tools/weekly_summary.py`, saves the report, and pops a notification via
`osascript`. No external apps required.

### Update the bot after a code change

```bash
ssh root@<VPS-IP>
sudo -u botuser git -C /home/botuser/binance-bot- pull
sudo -u botuser /home/botuser/binance-bot-/.venv/bin/pip install -q -r /home/botuser/binance-bot-/requirements.txt
systemctl restart binance-bot
journalctl -u binance-bot -f         # verify it came back up
```

### Stop the bot

```bash
systemctl stop binance-bot           # holds the service stopped
systemctl disable binance-bot        # also disables auto-start on reboot
```

---

## Failure modes the bot handles

| Failure | What happens | How the bot recovers |
|---|---|---|
| **Network hiccup** | API call raises | Outer try/except logs and retries after 60s |
| **macOS lid closes** | Process pauses | `caffeinate -i` keeps the system awake while the bot runs |
| **VPS reboots** | systemd starts the service automatically | State persists, bot resumes |
| **Bot crashes** | systemd's `Restart=on-failure` kicks in (max 5 in 5min) | State persists, bot resumes |
| **Sell fails (insufficient balance)** | `market_sell()` queries actual balance and caps to `min(state, actual)` | Sells what we actually have, drops the symbol from state |
| **Buy fails (min notional)** | Skips the buy, logs a warning | Tries again next cycle |
| **State drifts from exchange (testnet quirk)** | `reconcile_state_with_exchange()` at the start of every cycle | Updates state to match exchange; logs the diff |
| **Symbol not on testnet** | Filtered out at `pick_targets()` | Picks the next-best tradeable coin |
| **No coins pass trend filter** | Logs a warning, skips rebalance | Tries again next cycle |
| **Two bots on same testnet account** | Race conditions, fighting over orders | Don't do this — kill one before starting the other |

### Notes on Binance Spot Testnet quirks

The testnet is useful but has weird behaviours that don't exist on real
Binance:

- **Many altcoins are pre-seeded** with ~16,000–18,000 free units each. Buy
  orders add on top of these, inflating equity calculations.
- **Some coins have caps** — e.g., a buy of 132,401 D got truncated to
  ~18,446. State and reality diverge until reconciled.
- **Liquidity is thin** — fills can be slow or partial.
- **Symbol set differs** from mainnet — most overlap, a few don't.

The reconciliation logic + defensive sell handle all of these gracefully.
On real Binance, none of these quirks apply.

---

## Configuration knobs

Sensible defaults are baked in (best risk-adjusted config from the stress
test), but everything is tunable:

```bash
python -m src.rotation_bot \
  --top-k 5 \              # number of coins to hold at once
  --universe 25 \          # universe size (top N USDT pairs by volume)
  --timeframe 4h \         # bar size for momentum scoring
  --momentum-lookback 60 \ # bars used for momentum % return (60 × 4h ≈ 10 days)
  --rebalance-bars 6       # rebalance every N bars (6 on 4h = daily)
```

Other useful flags:

- `--dry-run` — log decisions but place no orders
- `--show-picks` — print current picks and exit
- `--once` — run a single rebalance cycle then exit
- `--regime-filter` — enable the BTC bull/bear macro filter
- `--regime-bear-alloc 0.5` — fraction of cash to deploy in bear regime (default 0.5; backtests favor it)

### Soft regime filter (recommended risk mitigation)

Backtests on the trustworthy bias-aware dataset:

| Config | 1y return | Max drawdown |
|---|---|---|
| No filter (baseline) | +44.1% | -67.4% |
| **Soft filter — 50% deployed in bear regimes** | **+44.2%** | **-56.4%** |
| Hard filter — 0% deployed in bear (full exit) | +13.2% | -61.4% |

The soft filter keeps the same return as no-filter while reducing the worst drawdown by 11 percentage points. It works by *not liquidating existing positions* but *only deploying half the cash for new picks during BTC bear regimes*. Avoids the whipsaw losses of binary on/off.

Enable it with:
```bash
python -m src.rotation_bot --regime-filter --regime-bear-alloc 0.5
```

### Environment variables (.env)

```
BINANCE_API_KEY=...        # testnet by default
BINANCE_API_SECRET=...
BINANCE_LIVE=false         # set true ONLY when ready for real funds
```

---

## Going live (eventually)

After **at least 30 days** of testnet running where live results track
backtest expectations:

1. Generate **real** Binance API keys (not testnet) — restrict to "spot
   trading", IP-allowlist your VPS
2. Set `BINANCE_LIVE=true` in `.env`
3. Restart the bot

The bot will print a 5-second warning before any live order. It will refuse
to deploy below ~$6 per position (Binance min notional).

**Do not go live before you can sit through a -30% drawdown without
touching anything.** That's the actual test of whether you should run this
with real money. The testnet exists specifically to find out where your
emotional limits are while it's still cheap.

---

## DCA bot for stocks/ETFs (bonus)

The repo includes a second bot that auto-buys ETFs every Friday with an
optional **tactical multiplier** (buys more when the market is down).
Diversifies your portfolio away from pure-crypto exposure.

📖 **Full guide: [`deploy/DCA.md`](deploy/DCA.md)**

Three modes: `simulation` (no broker, just logs), `paper` (IBKR paper
trading), `live` (real money via Interactive Brokers). Start in
simulation — it lets you validate the strategy without an IBKR account
or any real money.

```bash
.venv/bin/python -m src.dca_bot --dry-run         # preview
.venv/bin/python -m src.dca_bot                   # buy in simulation mode
bash tools/install_dca_schedule.sh                # schedule weekly Fri 16:00
```

The dashboard adds a **DCA bot** section showing total invested, current
value, P&L per ticker, and recent buys.

## Roadmap

- [x] **Fix survivorship bias in backtests** — point-in-time universe via `--bias-aware`
- [x] **Self-healing state reconciliation** — `reconcile_state_with_exchange()`
- [x] **Defensive sells** — `min(state, actual_balance)`
- [x] **VPS deployment** — `deploy/setup.sh` + systemd unit
- [x] **Sync script** — pull state from VPS to Mac for the dashboard
- [x] **Weekly summary notification** — `launchd` job posts a macOS notification every Sunday
- [x] **True P&L tracking** — `units_bought` + `cost_basis` preserved through reconcile so the dashboard shows real strategy performance, not testnet-seed-inflated numbers
- [x] **DCA bot for stocks/ETFs** — `src/dca_bot.py` with simulation/paper/live modes + tactical multiplier
- [x] **Soft regime filter** — `--regime-filter --regime-bear-alloc 0.5` deploys 50% of cash during BTC bear regimes. Backtests show same return, ~17% lower max drawdown.
- [ ] Include delisted coins in candidate pool (truly bias-free backtest)
- [ ] Multi-lookback momentum (combine 20/40/60-bar ranks for robustness)
- [ ] Walk-forward parameter optimization
- [ ] Telegram/email alerts on rebalance and big drawdowns
- [ ] SQLite for state instead of JSON
- [ ] Web-deployed dashboard with auth (so it works from anywhere)

---

## Safety rules

1. **`BINANCE_LIVE=false` by default.** Flipping it is the only way to touch real money.
2. **`.env` is gitignored.** Never commit keys.
3. **The repo is private.** Keep it that way — public repos with `BINANCE_API_KEY=` patterns get scraped within minutes.
4. **The bot only manages what it bought.** Pre-existing testnet balances are ignored, so the bot won't touch coins you put there manually.
5. **Position state persists.** Restarting the bot mid-position picks up where it left off; deleting `data/rotation_state.json` resets the bot's view (positions on the exchange remain).
6. **The reconcile step is non-negotiable.** If you remove it, you'll re-introduce the entire class of state-drift bugs.
7. **VPS keys ≠ Mac keys.** Use a separate testnet API key on the VPS so you can revoke one without taking down the other.

---

## Project status

Personal research project. Not maintained for production use. Use at your
own risk. If this is useful to you, fork it. If you find a bug, open an
issue.

Built in collaboration with Claude Code.

# 📊 Dashboard guide

A walkthrough of every section of the Streamlit dashboard — what it shows,
where the data comes from, and how to read it.

---

## How to open it

```bash
cd /Users/agneschan/Documents/00-Personal/Web/binance
source .venv/bin/activate
streamlit run dashboard/app.py
```

Opens automatically at **http://localhost:8501**. To stop: Ctrl+C in the
terminal.

The dashboard auto-refreshes every 30 seconds by default (configurable in
the sidebar). Live prices update on each refresh; the equity-curve chart
only updates when new rebalance snapshots come in.

---

## Layout (top to bottom)

```
┌─────────────────────────────────────────────────────────────────┐
│ ◐ Rotation                       Testnet · ● Healthy · 12m      │   topbar
├─────────────────────────────────────────────────────────────────┤
│  YOU PUT IN     CURRENT VALUE        💰 PROFIT                  │
│  $10,000.00     $13,441.50          +$3,441.50 (+34.42%)        │   hero card
├─────────────────────────────────────────────────────────────────┤
│  vs BTC HODL │ Cash USDT │ Positions │ BTC price                │   secondary
├─────────────────────────────────────────────────────────────────┤
│                                  │                              │
│   📈 EQUITY CHART                │   🥧 PORTFOLIO MIX           │
│   (interactive, hover for info)  │   (donut + total in middle)  │
│                                  │                              │
├─────────────────────────────────────────────────────────────────┤
│   💼 HOLDINGS                                                   │
│   table: symbol, units, entry, current, P&L %, P&L $, value     │
├─────────────────────────────────────────────────────────────────┤
│   🔍 LIVE SCANNER  (toggle in sidebar)                          │
├─────────────────────────────────────────────────────────────────┤
│   📜 RECENT REBALANCES                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. Topbar

```
◐ Rotation · Tue 28 Apr · 12:30        Testnet · ● Healthy · 12m
```

**Brand mark + clock**: just a label and the current time on your Mac.

**Mode pill** (gray):
- `Testnet` = the bot is using fake money (Binance Spot Testnet)
- `Live` = real money (only if `BINANCE_LIVE=true` is set in `.env`)

**Status pill** (color-coded):

| Pill | Meaning | When |
|---|---|---|
| 🟢 **Healthy** *(pulsing dot)* | Last rebalance < 25h ago | Normal operation |
| 🟡 **Late** | 25–48h since last rebalance | Bot may be paused (laptop sleep) or had an error |
| 🔴 **Stale** | >48h since last rebalance | Bot is probably dead — investigate |
| ⚪ **Unknown** | No rebalance has ever happened | First start, or state file missing |

The number after the pill (`12m`, `4.2h`) is **time since last rebalance**.

---

## 2. Hero card — the headline P&L

Three columns, large typography, designed so you can read the number from
across the room:

| Column | What it shows |
|---|---|
| **You put in** | Your starting cash. Set in the sidebar (`Money you put in`). Persists across restarts in `data/dashboard_config.json`. |
| **Strategy value** | "True" equity = USDT cash + sum of `units_bought × current price` for each holding. Uses what the bot actually purchased, **not** what's currently on the exchange. |
| **True Profit / Loss** | The big number. `Strategy value − You put in`. Shown in **dollars** and **percent**. Green if positive, red if negative. |

### Why "True" P&L (vs "Reported" P&L)

The Binance Spot Testnet seeds every account with thousands of free units
of dozens of altcoins (a "starter pack"). When the bot buys ZBT, it gets
added on top of whatever the testnet pre-credited. The exchange's view of
your balance is `bot-bought + testnet-seeded`, but only the bot-bought
portion reflects strategy performance.

The hero card's headline number ignores the seed and shows what the
strategy actually did — which is what you'd see on real Binance, where no
seed coins exist.

If there's meaningful seed inflation (>$50 difference), a small note
appears below the hero showing the testnet account total alongside the
true number, e.g.:

> ⚠ Testnet account total: **$13,612.13** (inflated by **$4,794.94** of
> free testnet seed coins). The number above is what the strategy actually
> did — what you'd see on real Binance.

When you eventually flip `BINANCE_LIVE=true`, this note disappears
automatically (the inflation goes to ~$0 on real Binance) and the hero
just shows your real performance.

---

## 3. Secondary metric tiles

Four small cards giving you the next-most-important context numbers:

| Tile | Definition | Why it matters |
|---|---|---|
| **vs BTC HODL** | Your % return − what you'd have if you'd just bought and held BTC for the same period | The honest test of "is this strategy worth it?" Anything > 0 means you're beating the dumbest possible strategy. |
| **Cash USDT** | Free USDT in the testnet account | Should be near zero most of the time (the bot deploys cash on every rebalance). High cash means the bot couldn't deploy something — check logs. |
| **Positions** | Number of distinct coins held | Should equal your `--top-k` setting (default 5). If lower, the trend filter rejected some picks (rare). If higher, a sell failed at some point. |
| **BTC price** | Current BTC/USDT mid price | Pure context. Big BTC moves usually correlate with altcoin moves. |

> "vs BTC HODL" is the metric that matters most for evaluating the
> strategy. If after 6+ months you're not beating BTC HODL, the strategy
> isn't worth the complexity.

---

## 4. Equity chart (left, big)

**X-axis**: time. **Y-axis**: USDT value.

| Line | What it represents |
|---|---|
| 🖤 **Solid black/ink line with subtle fill** | Your strategy's equity over time |
| ⚪ **Dotted gray line** | "BTC HODL benchmark" — what you'd have if you'd put your starting cash entirely into BTC at the first data point and just held |
| **Dashed horizontal line at "start"** | Your starting cash, as reference |

### Interactive features

- **Hover any point on the strategy line**: rich tooltip pops up showing:
  - Timestamp (day, date, time)
  - Current equity
  - P&L in dollars
  - vs start (% return)
  - vs BTC HODL (your edge)
  - Drawdown (% below the previous peak — important risk metric)
  - Position count + the actual symbols held at that moment
- **Hover the dotted BTC line**: shows BTC HODL value at that point
- **Range buttons** (top-left of chart, appear once you have 2+ days of data):
  - `1d` `1w` `1m` `all` to zoom the time axis
- **Spike-line crosshairs**: vertical/horizontal dotted lines that follow your cursor
- **Scroll-to-zoom**: scroll wheel zooms into a region; double-click to reset
- **Click + drag**: pan around when zoomed in

### How to read it

| Pattern | What it means |
|---|---|
| Strategy line above BTC line | Strategy is beating buy-and-hold ✅ |
| Strategy line below BTC line | Strategy is losing to buy-and-hold ❌ — be patient or reconsider |
| Both lines down together | Crypto-wide drawdown (most coins fall together) |
| Strategy down, BTC up | Strategy picked the wrong rotation, or alts are bleeding while BTC pumps |
| Strategy up, BTC down | The dream — strategy avoided the BTC drop by being in stronger alts |
| Big drop + recovery | Drawdown event — normal for momentum strategies |

### Empty state

If you see "No equity history yet" — the bot hasn't logged a snapshot yet.
Snapshots are logged at every rebalance (~daily). On a brand-new install
you'll see this until the first rebalance fires.

---

## 5. Portfolio mix donut (right)

A donut chart showing **how your money is currently divided**:

- Each coin is a slice, sized by USDT value
- Cash (if any) is a gray slice
- The total equity is in the center
- Colors are a monochrome gray-scale palette

### How to read it

- **Roughly equal slices** = healthy equal-weight allocation (the bot
  defaults to spreading new cash equally across new picks)
- **One huge slice** = that coin pumped hard since you bought it. The bot
  doesn't auto-trim, so winners can become a big share of your portfolio
  until they're rotated out
- **Big gray "Cash" slice** = the bot has uninvested USDT. This is normal
  immediately after a sell if it didn't reinvest. Persistent high cash =
  something's wrong (likely a buy failed, check logs).

### Hover

Hovering a slice shows the symbol, exact USDT value, and percent of
portfolio.

---

## 6. Holdings table

Every position the bot is currently managing, sorted by value (largest first):

| Column | Meaning |
|---|---|
| **Symbol** | The coin (without `/USDT` suffix) |
| **Units** | How many units the bot **actually bought** (`units_bought`, ignores testnet seed) |
| **Cost** | USDT spent buying this position (cost basis) |
| **Entry** | Price per unit when the bot bought |
| **Current** | Live mid price right now |
| **P&L %** | `(Current − Entry) / Entry × 100` — shown as a colored progress bar |
| **P&L $** | Dollar P&L computed from `(Current × units_bought) − Cost` — the **true** dollar gain/loss |
| **True value** | `units_bought × Current` — what the bot's actual purchases are worth (excludes testnet seed) |
| **Weight** | Position's share of true equity, shown as a progress bar |

### Reading the P&L bars

The progress-bar columns (P&L %, Weight) show **relative magnitude** within
the table. The bar's full width is the range from the worst to the best
position. So even a coin that's slightly negative might show a partly-full
bar if the worst position is much more negative.

### Reading per-coin P&L correctly

The table now uses `units_bought` (what the bot actually purchased) rather
than the reconciled exchange balance. So:

- **P&L %** is `(current_price / entry_price − 1) × 100` — pure price
  performance since the bot bought
- **P&L $** is `units_bought × (current − entry)` — what the strategy
  actually earned/lost on this position
- **True value** is `units_bought × current` — what the strategy's
  purchases are worth (testnet seed excluded)

This is the same picture you'd see on real Binance.

---

## 7. Live scanner (toggle in sidebar)

Off by default to keep page loads fast. Toggle **"Run live scanner"** in
the sidebar — adds ~10 seconds to each refresh because it calls Binance to
score the entire universe live.

| Column | Meaning |
|---|---|
| **Symbol** | Coin (without `/USDT`) |
| **Held** | ✓ if the bot already owns this coin |
| **Tradeable** | ✓ if available on the configured exchange (testnet) |
| **Momentum** | % return over the last `--momentum-lookback` bars (default 60 × 4h ≈ 10 days). The strategy ranks by this. Shown as a progress bar. |
| **Above EMA** | How far the current price is above its 50-period EMA, in % — confirms uptrend strength |
| **ATR** | Average True Range as % of price — volatility proxy. Coins with very high ATR are riskier. |
| **24h** | 24-hour price change (from Binance ticker) |
| **Vol** | 24-hour USDT volume in millions |

### What to look for

- The **top 5 with both ✓ Tradeable and ✓ Held** = what the bot is currently
  doing. If they match, no rotation will happen on the next rebalance.
- A **Held coin that's NOT in the top 5** = will be sold at the next rebalance
- A **top-5 coin that's NOT held** = will be bought at the next rebalance
- A **top coin marked Tradeable: ✗** = won't be picked, the bot moves to the
  next eligible candidate

### Scanner controls (sidebar)

- **Scanner universe**: how many top USDT pairs to scan (default 25)
- **Top-N display**: how many results to show in the table (default 10)

---

## 8. Recent rebalances

The last 20 rebalance events from `data/equity_history.csv`, newest first:

| Column | Meaning |
|---|---|
| **When** | Date and time of the rebalance |
| **Equity** | Total portfolio value at that point |
| **Cash** | USDT cash at that point (usually near zero post-rebalance) |
| **Pos** | Number of positions held |
| **Return** | `(Equity − Starting Cash) / Starting Cash`, as a colored progress bar |
| **Symbols** | The coins held after this rebalance |

Use this to see the **rotation history**:
- Symbols changing row-to-row = the bot is rotating actively
- Same symbols for many rows = the strategy keeps picking the same coins
  (could be a sustained trend, or a stuck market)
- Equity trending up = strategy is working
- Equity trending down = strategy is in a drawdown phase

---

## Sidebar controls

Click the `>` on the top-left to expand the sidebar.

| Control | Effect |
|---|---|
| **Auto-refresh (s)** | How often the dashboard re-queries Binance and re-renders. 30s is the default. Set to 0 to disable auto-refresh (manual refresh only). |
| **Run live scanner** | Toggle the scanner section on/off. Slow (~10s) so off by default. |
| **Scanner universe** | How many top USDT pairs the scanner considers (10–50). |
| **Top-N display** | Rows shown in the scanner table (5–25). |
| **Money you put in (USDT)** | Your starting cash baseline for P&L calculation. Saved automatically to `data/dashboard_config.json`. |

---

## Where the data comes from

```
LIVE (refreshed every 15s):
  Binance API ──▶ fetch_balance()    → Cash USDT, position values
  Binance API ──▶ fetch_ticker()     → Current prices for hero card,
                                       holdings table, donut, BTC line

PERSISTED FILES (read on each refresh):
  data/rotation_state.json           → Holdings list, entry prices, last rebalance
  data/equity_history.csv            → Equity curve, BTC HODL benchmark, recent table
  data/dashboard_config.json         → Your starting cash setting

SCANNER (only when toggled on, fresh API call):
  Binance Mainnet ──▶ get_universe() → Top USDT pairs by 24h volume
  Binance Mainnet ──▶ scan()         → Score and rank all of them
```

The two persisted JSON/CSV files are written by the bot. If the bot is
running on a VPS, those files live there — sync them to your Mac to see
fresh chart data:

```bash
bash deploy/sync_from_vps.sh <VPS-IP>
```

---

## Common scenarios

### "My P&L is -10% and I'm panicking"

Look at:
- **Drawdown in chart hover**: is it within the bot's expected range
  (-30% to -50% in stress tests)?
- **vs BTC HODL tile**: are you down more than BTC also is? If both are
  down similarly, it's a market-wide event, not a strategy failure.
- **Recent rebalances**: did the bot rotate into the wrong coin recently?

If you're within stress-test bounds and BTC is also down, **do nothing**.
Momentum strategies need weeks/months to play out.

### "Bot status shows Late or Stale"

- **Late (25–48h)**: usually macOS sleep. If running on Mac, restart with
  `caffeinate -i nohup .venv/bin/python -m src.rotation_bot &`. If on VPS,
  SSH in and check `journalctl -u binance-bot -n 50`.
- **Stale (>48h)**: bot is probably crashed. SSH in (or check Mac
  process), look at logs, restart.

### "Scanner shows great picks but bot didn't buy them"

- The bot only rebalances on its scheduled cycle (default daily). The
  scanner shows what *would* be picked right now, but no action happens
  until the next rebalance.
- A pick may be marked `Tradeable: ✗` if it's not on testnet.
- If you need an immediate rebalance: SSH to VPS and run
  `systemctl restart binance-bot` — it'll rebalance immediately on startup.

### "Holdings table shows 6 positions but top-k is 5"

Probably a sell failed somewhere, leaving an extra coin. The
`reconcile_state_with_exchange` runs at the start of every rebalance and
will retry the sell on the next cycle. It usually self-fixes within 24h.

### "Equity curve has a big jump that looks wrong"

Check `data/weekly_reports/all_reports.log` for context. Sudden jumps can
be caused by:
- A coin pumping hard (real)
- State drift being reconciled (the equity number suddenly reflects reality)
- A new equity snapshot being written after a long pause

---

## Troubleshooting

### Dashboard won't load (`HTTP 500` or blank page)

```bash
# Stop streamlit and restart in foreground to see errors
kill $(cat /tmp/streamlit.pid) 2>/dev/null
.venv/bin/streamlit run dashboard/app.py
```

Look at the terminal output for tracebacks.

### Hero card says `$0.00` for current value

Probably the testnet API call is failing. Check:
- `.env` has valid `BINANCE_API_KEY` and `BINANCE_API_SECRET`
- Internet works
- Try `python -c "from src.exchange import get_exchange; print(get_exchange().fetch_balance().get('USDT'))"`

### "vs BTC HODL" shows weird values

The benchmark uses the BTC price at the **first equity_history.csv row**
as its baseline. If your history starts at a moment when BTC was unusually
high or low, the comparison can be skewed for a while. After more
rebalances accumulate, this stabilizes.

### Empty equity chart

You either:
- Haven't had a rebalance yet on this machine (wait or run
  `python -m src.rotation_bot --once`)
- Have the bot on a VPS and need to sync:
  `bash deploy/sync_from_vps.sh <VPS-IP>`

---

## Notes

- The dashboard is **read-only**. It never sends orders or modifies bot state.
  You can have it open while the bot runs — they don't interfere.
- Two browser tabs open the same dashboard each make their own API calls
  to Binance — usually fine, but if you see rate-limit errors, close one.
- The dashboard's "Cash USDT" only counts free USDT, not USDT locked in
  open orders. The bot uses market orders, so this should be close to
  true cash at any given moment.

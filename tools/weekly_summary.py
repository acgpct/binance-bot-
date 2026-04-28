"""Generate a concise weekly summary of the rotation bot's performance.

Reads:
  - data/rotation_state.json   (current holdings, last rebalance)
  - data/equity_history.csv    (equity snapshots over time)
  - data/dashboard_config.json (starting cash)
  - Live testnet balance via the Binance API (using local .env)

Outputs:
  - A short text report to stdout (≤ 250 words, friendly tone)
  - A one-line summary suitable for a macOS notification on the last line,
    prefixed with `NOTIFY:` so the wrapper script can extract it

Designed to be called from a launchd job; safe to run manually too.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import get_exchange  # noqa: E402

STATE_PATH = ROOT / "data" / "rotation_state.json"
EQUITY_LOG_PATH = ROOT / "data" / "equity_history.csv"
DASH_CONFIG_PATH = ROOT / "data" / "dashboard_config.json"


def load_starting_cash() -> float:
    if DASH_CONFIG_PATH.exists():
        cfg = json.loads(DASH_CONFIG_PATH.read_text())
        return float(cfg.get("starting_cash", 10_000.0))
    return 10_000.0


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"holdings": {}, "last_rebalance": None}


def load_history() -> pd.DataFrame:
    if not EQUITY_LOG_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(EQUITY_LOG_PATH, parse_dates=["timestamp"]).sort_values("timestamp")


def main() -> int:
    starting = load_starting_cash()
    state = load_state()
    holdings = state.get("holdings", {})
    hist = load_history()

    try:
        ex = get_exchange()
        bal = ex.fetch_balance()
        cash = float(bal.get("USDT", {}).get("free", 0.0))
        coin_pnl = []  # (symbol, pnl_pct, value)
        equity = cash
        for sym, info in holdings.items():
            ticker = ex.fetch_ticker(sym)
            current = float(ticker["last"])
            entry = float(info.get("entry_price", 0)) or current
            units = float(info.get("units", 0))
            value = units * current
            equity += value
            pnl_pct = (current / entry - 1) * 100 if entry > 0 else 0
            coin_pnl.append((sym.replace("/USDT", ""), pnl_pct, value))
        btc_now = float(ex.fetch_ticker("BTC/USDT")["last"])
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Could not reach Binance API: {e}")
        print("NOTIFY: Weekly report failed — check API connection")
        return 1

    pnl_usd = equity - starting
    pnl_pct = (equity / starting - 1) * 100 if starting > 0 else 0.0

    # Week-over-week
    wow_str = "no prior data"
    if len(hist) >= 2:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        prior = hist[hist["timestamp"] <= cutoff]
        prior_equity = float(prior["equity"].iloc[-1]) if len(prior) else float(hist["equity"].iloc[0])
        wow_change = equity - prior_equity
        wow_pct = (equity / prior_equity - 1) * 100 if prior_equity > 0 else 0
        wow_str = f"${wow_change:+,.2f} ({wow_pct:+.2f}%)"

    # BTC benchmark (since first equity log)
    edge_str = "n/a"
    if len(hist) and hist["btc_price"].iloc[0] > 0:
        btc_at_start = float(hist["btc_price"].iloc[0])
        btc_pct = (btc_now / btc_at_start - 1) * 100
        edge = pnl_pct - btc_pct
        edge_str = f"{edge:+.2f}% (you {pnl_pct:+.2f}% vs BTC {btc_pct:+.2f}%)"

    # Best / worst coins
    best, worst = None, None
    if coin_pnl:
        coin_pnl.sort(key=lambda x: x[1])
        worst = coin_pnl[0]
        best = coin_pnl[-1]

    # Bot health
    health = "Unknown"
    last_reb = state.get("last_rebalance")
    if last_reb:
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last_reb)).total_seconds() / 3600
        if hours < 25:
            health = f"Healthy ({hours:.1f}h since last rebalance)"
        elif hours < 48:
            health = f"⚠️  Late ({hours:.1f}h since last rebalance — should be <25h)"
        else:
            health = f"❌ Stale ({hours:.0f}h since last rebalance — bot may be down)"

    # Drawdown check
    dd_warning = ""
    if len(hist):
        peak = float(hist["equity"].max())
        peak_dd = (equity / peak - 1) * 100 if peak > 0 else 0
        if peak_dd < -25:
            dd_warning = f"\n🚨 Drawdown alert: equity is {peak_dd:.1f}% below peak (${peak:,.2f}). Consider reviewing."

    # ----- Build the report -----
    direction = "📈 up" if pnl_usd >= 0 else "📉 down"
    today = datetime.now().strftime("%a %d %b")

    report_lines = [
        f"🤖 Rotation Bot — Weekly Report ({today})",
        "─" * 48,
        f"You put in:    ${starting:,.2f}",
        f"Now worth:     ${equity:,.2f}",
        f"P&L:           ${pnl_usd:+,.2f} ({pnl_pct:+.2f}%) — {direction} from start",
        f"This week:     {wow_str}",
        f"vs BTC HODL:   {edge_str}",
        "",
        f"Holdings ({len(holdings)}):",
    ]
    if not holdings:
        report_lines.append("  (none)")
    else:
        for sym, info in sorted(holdings.items()):
            base = sym.replace("/USDT", "")
            report_lines.append(f"  {base}")
        if best and worst and best[0] != worst[0]:
            report_lines.append("")
            report_lines.append(f"🏆 Best:  {best[0]} {best[1]:+.2f}%")
            report_lines.append(f"📉 Worst: {worst[0]} {worst[1]:+.2f}%")

    report_lines.extend(["", f"Bot status: {health}"])
    if dd_warning:
        report_lines.append(dd_warning)

    report_lines.extend([
        "",
        "Open the dashboard for details:  streamlit run dashboard/app.py",
    ])

    print("\n".join(report_lines))

    # One-line summary for the macOS notification (fits in ~256 chars)
    notify_summary = (
        f"P&L ${pnl_usd:+,.0f} ({pnl_pct:+.1f}%). "
        f"Week: {wow_str.split()[0] if wow_str != 'no prior data' else 'first week'}. "
        f"vs BTC: {edge_str.split()[0]}."
    )
    print(f"NOTIFY: {notify_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

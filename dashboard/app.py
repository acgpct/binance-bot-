"""Streamlit dashboard for the rotation bot.

Run:  streamlit run dashboard/app.py
Then open http://localhost:8501 in your browser.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Allow `from src.foo` imports when run with `streamlit run dashboard/app.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exchange import get_exchange, get_data_exchange, is_live  # noqa: E402
from src.scanner import get_universe, scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "rotation_state.json"
EQUITY_LOG_PATH = ROOT / "data" / "equity_history.csv"
DASH_CONFIG_PATH = ROOT / "data" / "dashboard_config.json"


def load_dash_config() -> dict:
    if DASH_CONFIG_PATH.exists():
        return json.loads(DASH_CONFIG_PATH.read_text())
    return {"starting_cash": 10_000.0}


def save_dash_config(cfg: dict) -> None:
    DASH_CONFIG_PATH.parent.mkdir(exist_ok=True)
    DASH_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

st.set_page_config(page_title="Rotation Bot", page_icon="🤖", layout="wide")

# ----------------------------------------------------------------------
# Sidebar — controls + autorefresh
# ----------------------------------------------------------------------
st.sidebar.title("⚙️ Controls")
refresh_secs = st.sidebar.slider("Auto-refresh (seconds)", 0, 300, 30, step=10,
                                 help="0 = no auto-refresh. Browser will reload data on this interval.")
if refresh_secs > 0:
    st_autorefresh(interval=refresh_secs * 1000, key="dash_refresh")

show_scanner = st.sidebar.checkbox("Run live scanner (slow, ~10s)", value=False,
                                   help="Calls Binance to score the current universe. Disable for faster page loads.")
scanner_universe = st.sidebar.slider("Scanner universe size", 10, 50, 25, step=5)
scanner_top_n = st.sidebar.slider("Scanner top-N to display", 5, 25, 10, step=1)

dash_cfg = load_dash_config()
starting_cash = st.sidebar.number_input(
    "💰 Money you put in (USDT)", value=float(dash_cfg.get("starting_cash", 10_000.0)),
    step=100.0, help="Your initial deposit. Used to compute P&L. Saved between sessions.",
)
if starting_cash != dash_cfg.get("starting_cash"):
    save_dash_config({**dash_cfg, "starting_cash": starting_cash})

# ----------------------------------------------------------------------
# Load state and exchange
# ----------------------------------------------------------------------
@st.cache_resource
def get_exchanges():
    return get_exchange(), get_data_exchange()

trade_exchange, data_exchange = get_exchanges()


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"holdings": {}, "last_rebalance": None}


def load_equity_history() -> pd.DataFrame:
    if not EQUITY_LOG_PATH.exists():
        return pd.DataFrame(columns=["timestamp", "equity", "cash", "btc_price", "n_positions", "holdings"])
    df = pd.read_csv(EQUITY_LOG_PATH, parse_dates=["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


@st.cache_data(ttl=20)
def fetch_balance():
    return trade_exchange.fetch_balance()


@st.cache_data(ttl=20)
def fetch_ticker(symbol: str) -> dict:
    return trade_exchange.fetch_ticker(symbol)


def current_equity(holdings: dict) -> tuple[float, float, dict]:
    """Return (cash, total_equity, per_symbol_value_dict) from current testnet prices."""
    bal = fetch_balance()
    cash = float(bal.get("USDT", {}).get("free", 0.0))
    pos_values = {}
    for sym, info in holdings.items():
        try:
            t = fetch_ticker(sym)
            pos_values[sym] = float(info.get("units", 0)) * float(t["last"])
        except Exception:
            pos_values[sym] = 0.0
    return cash, cash + sum(pos_values.values()), pos_values


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------
mode_label = "🔴 LIVE (real money)" if is_live() else "🟢 TESTNET"
st.title("🤖 Rotation Bot Dashboard")
st.caption(f"Mode: **{mode_label}**  ·  Last refresh: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
           f"  ·  Auto-refresh: {refresh_secs}s" if refresh_secs > 0 else f"Mode: {mode_label}  ·  Auto-refresh OFF")

state = load_state()
holdings = state.get("holdings", {})
last_reb = state.get("last_rebalance")

cash, equity, pos_values = current_equity(holdings)
pnl_usd = equity - starting_cash
pnl_pct = (equity / starting_cash - 1) * 100 if starting_cash > 0 else 0.0

# BTC benchmark
hist = load_equity_history()
btc_now = float(fetch_ticker("BTC/USDT")["last"])
btc_at_start = float(hist["btc_price"].iloc[0]) if len(hist) and hist["btc_price"].iloc[0] > 0 else btc_now
btc_return_pct = (btc_now / btc_at_start - 1) * 100

# Bot health
bot_alive = "Unknown"
mins_since = None
if last_reb:
    mins_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last_reb)).total_seconds() / 60
    if mins_since < 60 * 25:
        bot_alive = "✅ Healthy"
    elif mins_since < 60 * 48:
        bot_alive = "⚠️ Late"
    else:
        bot_alive = "❌ Stale (>48h)"

# ----------------------------------------------------------------------
# 💰 HERO P&L — the big number you actually came here to see
# ----------------------------------------------------------------------
pnl_color = "#2ecc71" if pnl_usd >= 0 else "#e74c3c"
pnl_sign = "+" if pnl_usd >= 0 else "−"
pnl_emoji = "📈" if pnl_usd >= 0 else "📉"

st.markdown(
    f"""
    <div style="background: linear-gradient(135deg, #1a1d23 0%, #2c3038 100%);
                border-radius: 16px; padding: 28px 32px; margin: 8px 0 16px 0;
                border: 1px solid #333;">
      <div style="display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: 16px; align-items: center;">
        <div>
          <div style="color:#888; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">Money you put in</div>
          <div style="color:#eee; font-size:36px; font-weight:600; margin-top:6px;">${starting_cash:,.2f}</div>
        </div>
        <div>
          <div style="color:#888; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">Current value</div>
          <div style="color:#eee; font-size:36px; font-weight:600; margin-top:6px;">${equity:,.2f}</div>
        </div>
        <div style="border-left: 1px solid #333; padding-left: 24px;">
          <div style="color:#888; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">{pnl_emoji} You've {'earned' if pnl_usd >= 0 else 'lost'}</div>
          <div style="color:{pnl_color}; font-size:48px; font-weight:700; margin-top:4px; line-height:1;">
            {pnl_sign}${abs(pnl_usd):,.2f}
          </div>
          <div style="color:{pnl_color}; font-size:20px; font-weight:500; margin-top:6px;">
            {pnl_sign}{abs(pnl_pct):.2f}%
          </div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------
# Secondary metrics row
# ----------------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("vs BTC HODL", f"{pnl_pct - btc_return_pct:+.2f}%",
          help=f"Strategy: {pnl_pct:+.2f}% · BTC over same period: {btc_return_pct:+.2f}%")
k2.metric("Cash (USDT)", f"${cash:,.2f}")
k3.metric("Positions", str(len(holdings)))
k4.metric("Last rebalance",
          f"{mins_since:.0f} min ago" if mins_since is not None else "—",
          help=last_reb or "Bot has not run a real rebalance yet")
k5.metric("Bot status", bot_alive)

st.divider()

# ----------------------------------------------------------------------
# Equity curve
# ----------------------------------------------------------------------
left, right = st.columns([2, 1])

with left:
    st.subheader("📈 Equity over time")
    if len(hist) == 0:
        st.info("No equity history yet. The bot logs a snapshot at each rebalance — "
                "wait for the first rebalance, or run `python -m src.rotation_bot --once`.")
    else:
        # Compose strategy + BTC-benchmark curves
        plot_df = hist.copy()
        plot_df["btc_benchmark"] = starting_cash * (plot_df["btc_price"] / plot_df["btc_price"].iloc[0])

        # Append "now" point
        now_row = pd.DataFrame([{
            "timestamp": datetime.now(timezone.utc),
            "equity": equity,
            "cash": cash,
            "btc_price": btc_now,
            "n_positions": len(holdings),
            "holdings": "|".join(holdings.keys()),
            "btc_benchmark": starting_cash * (btc_now / plot_df["btc_price"].iloc[0]),
        }])
        plot_df = pd.concat([plot_df, now_row], ignore_index=True)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=plot_df["timestamp"], y=plot_df["equity"],
                                 name="Strategy", mode="lines+markers", line={"color": "#2ecc71", "width": 2.5}))
        fig.add_trace(go.Scatter(x=plot_df["timestamp"], y=plot_df["btc_benchmark"],
                                 name="BTC HODL benchmark", mode="lines", line={"color": "#f39c12", "dash": "dash"}))
        fig.add_hline(y=starting_cash, line_dash="dot", line_color="gray", annotation_text="starting cash")
        fig.update_layout(height=400, hovermode="x unified",
                          margin={"l": 0, "r": 0, "t": 10, "b": 0},
                          yaxis_title="USDT", xaxis_title=None,
                          legend={"orientation": "h", "yanchor": "bottom", "y": 1.02})
        st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("💼 Portfolio mix")
    if not holdings:
        st.info("No open positions.")
    else:
        labels = list(pos_values.keys()) + (["Cash (USDT)"] if cash > 0 else [])
        values = list(pos_values.values()) + ([cash] if cash > 0 else [])
        fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.55,
                                     textinfo="label+percent", insidetextorientation="radial")])
        fig.update_layout(height=400, margin={"l": 0, "r": 0, "t": 10, "b": 0},
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# ----------------------------------------------------------------------
# Current holdings table with per-coin P&L
# ----------------------------------------------------------------------
st.subheader("📊 Current holdings")
if not holdings:
    st.info("No open positions. The bot will buy at the next rebalance.")
else:
    rows = []
    for sym, info in holdings.items():
        units = float(info.get("units", 0))
        entry = float(info.get("entry_price", 0))
        try:
            current = float(fetch_ticker(sym)["last"])
        except Exception:
            current = entry
        value = units * current
        pnl_pct = (current / entry - 1) * 100 if entry > 0 else 0
        pnl_usd = value - units * entry
        rows.append({
            "Symbol": sym,
            "Units": units,
            "Entry $": entry,
            "Current $": current,
            "P&L %": pnl_pct,
            "P&L $": pnl_usd,
            "Value $": value,
            "% of port": value / equity * 100 if equity > 0 else 0,
            "Entered": info.get("entered_at", "")[:19].replace("T", " "),
        })
    holdings_df = pd.DataFrame(rows).sort_values("Value $", ascending=False)
    st.dataframe(
        holdings_df.style.format({
            "Units": "{:,.4f}", "Entry $": "${:,.4f}", "Current $": "${:,.4f}",
            "P&L %": "{:+.2f}%", "P&L $": "${:+,.2f}",
            "Value $": "${:,.2f}", "% of port": "{:.1f}%",
        }).map(lambda v: f"color: {'#2ecc71' if v > 0 else '#e74c3c'}",
               subset=["P&L %", "P&L $"]),
        use_container_width=True, hide_index=True,
    )

# ----------------------------------------------------------------------
# Live scanner
# ----------------------------------------------------------------------
st.subheader("🔍 Live scanner picks")
if show_scanner:
    with st.spinner(f"Scanning top {scanner_universe} USDT pairs (this takes ~10s)..."):
        try:
            universe = get_universe(data_exchange, top_n=scanner_universe, min_volume_usd=5_000_000)
            scan_df = scan(data_exchange, universe, timeframe="4h", days=14, momentum_lookback=60)
            if len(scan_df):
                trade_exchange.load_markets()
                tradeable = set(trade_exchange.symbols)
                scan_df["tradeable"] = scan_df["symbol"].isin(tradeable)
                scan_df["currently_held"] = scan_df["symbol"].isin(holdings.keys())
                cols = ["symbol", "currently_held", "tradeable", "momentum_pct",
                        "above_long_pct", "atr_pct", "change_24h_pct", "quote_volume_m", "last_price"]
                st.dataframe(
                    scan_df[cols].head(scanner_top_n).style.format({
                        "momentum_pct": "{:+.2f}%", "above_long_pct": "{:+.2f}%",
                        "atr_pct": "{:.2f}%", "change_24h_pct": "{:+.2f}%",
                        "quote_volume_m": "${:.0f}M", "last_price": "${:,.4f}",
                    }), use_container_width=True, hide_index=True,
                )
                st.caption(f"✓ = currently held by bot. Bot will pick top-K *tradeable* uptrending coins at next rebalance.")
            else:
                st.warning("No coins passed the trend filter right now.")
        except Exception as e:
            st.error(f"Scanner failed: {e}")
else:
    st.info("Scanner is disabled — toggle 'Run live scanner' in the sidebar to enable.")

# ----------------------------------------------------------------------
# Recent rebalance history
# ----------------------------------------------------------------------
st.subheader("📜 Rebalance history")
if len(hist) == 0:
    st.info("No rebalances logged yet.")
else:
    display = hist.copy().tail(20).iloc[::-1]
    display["timestamp"] = display["timestamp"].dt.strftime("%Y-%m-%d %H:%M UTC")
    display["return_since_start_%"] = (display["equity"] / starting_cash - 1) * 100
    st.dataframe(
        display[["timestamp", "equity", "cash", "n_positions", "holdings",
                 "btc_price", "return_since_start_%"]].style.format({
            "equity": "${:,.2f}", "cash": "${:,.2f}",
            "btc_price": "${:,.0f}", "return_since_start_%": "{:+.2f}%",
        }), use_container_width=True, hide_index=True,
    )

# ----------------------------------------------------------------------
# Footer
# ----------------------------------------------------------------------
st.divider()
st.caption(f"State file: `{STATE_PATH.relative_to(ROOT)}` · "
           f"Equity log: `{EQUITY_LOG_PATH.relative_to(ROOT)}` · "
           f"Bot: `python -m src.rotation_bot`")

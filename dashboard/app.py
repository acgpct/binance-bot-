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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exchange import get_exchange, get_data_exchange, is_live  # noqa: E402
from src.scanner import get_universe, scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "rotation_state.json"
EQUITY_LOG_PATH = ROOT / "data" / "equity_history.csv"
DASH_CONFIG_PATH = ROOT / "data" / "dashboard_config.json"

# ---------- Minimalist palette ----------
INK = "#0f172a"           # near-black for headlines
TEXT = "#1e293b"          # body text
MUTED = "#64748b"          # secondary text
SUBTLE = "#94a3b8"         # tertiary
HAIR = "#e2e8f0"           # hairline borders
CARD = "#ffffff"           # card background
SOFT = "#f8fafc"           # subtle panel
BG = "#ffffff"             # page background

GREEN = "#059669"
RED = "#dc2626"
AMBER = "#d97706"
ACCENT = "#0f172a"         # use INK as accent for monochrome aesthetic

st.set_page_config(
    page_title="Rotation",
    page_icon="◐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- Custom CSS — clean, minimalist, Linear/Stripe-inspired ----------
st.markdown(
    f"""
    <style>
    @import url('https://rsms.me/inter/inter.css');
    html, body, [class*="css"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        -webkit-font-smoothing: antialiased;
    }}
    .stApp {{ background: {BG}; }}
    .block-container {{
        padding-top: 2.4rem;
        padding-bottom: 3rem;
        max-width: 1200px;
    }}
    h1, h2, h3, h4 {{
        font-weight: 600;
        letter-spacing: -0.02em;
        color: {INK};
    }}
    h2 {{
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: {MUTED};
        margin-top: 2.4rem;
        margin-bottom: 0.8rem;
    }}
    /* Streamlit metric tiles */
    [data-testid="stMetric"] {{
        background: {CARD};
        border: 1px solid {HAIR};
        border-radius: 12px;
        padding: 16px 20px;
    }}
    [data-testid="stMetricLabel"] {{
        color: {MUTED} !important;
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 500;
    }}
    [data-testid="stMetricValue"] {{
        font-size: 1.35rem;
        font-weight: 600;
        color: {INK};
        font-feature-settings: 'tnum';
    }}
    [data-testid="stMetricDelta"] {{
        font-size: 0.78rem;
    }}
    /* Dataframes */
    div[data-testid="stDataFrame"] {{
        border: 1px solid {HAIR};
        border-radius: 12px;
        overflow: hidden;
    }}
    div[data-testid="stDataFrame"] [data-testid="stTable"] {{
        background: {CARD};
    }}
    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background: {SOFT};
        border-right: 1px solid {HAIR};
    }}
    /* Pill / status */
    .pill {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 500;
        letter-spacing: 0.01em;
        border: 1px solid;
    }}
    .pill-healthy {{ background: #ecfdf5; color: {GREEN}; border-color: #a7f3d0; }}
    .pill-late {{ background: #fffbeb; color: {AMBER}; border-color: #fde68a; }}
    .pill-stale {{ background: #fef2f2; color: {RED}; border-color: #fecaca; }}
    .pill-mode {{ background: {SOFT}; color: {MUTED}; border-color: {HAIR}; }}
    .dot {{
        display: inline-block;
        width: 6px; height: 6px;
        border-radius: 50%;
    }}
    .pulse-green {{ animation: pulse 2.4s infinite; }}
    @keyframes pulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(5,150,105,0.5); }}
        70% {{ box-shadow: 0 0 0 6px rgba(5,150,105,0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(5,150,105,0); }}
    }}
    /* Hero card */
    .hero {{
        background: {CARD};
        border: 1px solid {HAIR};
        border-radius: 16px;
        padding: 32px 36px;
        margin-bottom: 24px;
    }}
    .hero-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr 1.4fr;
        gap: 32px;
        align-items: start;
    }}
    .hero-label {{
        color: {MUTED};
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 500;
        margin-bottom: 6px;
    }}
    .hero-value {{
        color: {INK};
        font-size: 1.6rem;
        font-weight: 600;
        font-feature-settings: 'tnum';
        letter-spacing: -0.02em;
    }}
    .hero-pnl {{
        font-size: 2.4rem;
        font-weight: 700;
        font-feature-settings: 'tnum';
        letter-spacing: -0.03em;
        line-height: 1.1;
    }}
    .hero-pnl-pct {{
        font-size: 1rem;
        font-weight: 500;
        margin-top: 4px;
        font-feature-settings: 'tnum';
    }}
    .hero-divider {{
        border-left: 1px solid {HAIR};
        padding-left: 32px;
    }}
    /* Footer */
    .footer {{
        color: {SUBTLE};
        font-size: 0.72rem;
        text-align: center;
        margin-top: 40px;
        padding-top: 24px;
        border-top: 1px solid {HAIR};
    }}
    .footer code {{
        background: {SOFT};
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.7rem;
    }}
    /* Header */
    .topbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 28px;
    }}
    .brand {{
        display: flex;
        align-items: baseline;
        gap: 10px;
    }}
    .brand-mark {{
        font-size: 1.6rem;
        font-weight: 700;
        color: {INK};
        letter-spacing: -0.04em;
    }}
    .brand-meta {{
        color: {MUTED};
        font-size: 0.78rem;
    }}
    /* Plotly chart wrapper */
    .js-plotly-plot {{
        border: 1px solid {HAIR};
        border-radius: 12px;
        background: {CARD};
        padding: 4px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Helpers ----------
def load_dash_config() -> dict:
    if DASH_CONFIG_PATH.exists():
        return json.loads(DASH_CONFIG_PATH.read_text())
    return {"starting_cash": 10_000.0}


def save_dash_config(cfg: dict) -> None:
    DASH_CONFIG_PATH.parent.mkdir(exist_ok=True)
    DASH_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"holdings": {}, "last_rebalance": None}


def load_equity_history() -> pd.DataFrame:
    if not EQUITY_LOG_PATH.exists():
        return pd.DataFrame(columns=["timestamp", "equity", "cash", "btc_price", "n_positions", "holdings"])
    df = pd.read_csv(EQUITY_LOG_PATH, parse_dates=["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


@st.cache_resource
def get_exchanges():
    return get_exchange(), get_data_exchange()


trade_exchange, data_exchange = get_exchanges()


@st.cache_data(ttl=15)
def fetch_balance():
    return trade_exchange.fetch_balance()


@st.cache_data(ttl=15)
def fetch_ticker(symbol: str) -> dict:
    return trade_exchange.fetch_ticker(symbol)


def current_equity(holdings: dict) -> tuple[float, float, dict]:
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


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("##### Controls")
    refresh_secs = st.slider("Auto-refresh (s)", 0, 300, 30, step=10)
    if refresh_secs > 0:
        st_autorefresh(interval=refresh_secs * 1000, key="dash_refresh")
    show_scanner = st.checkbox("Run live scanner", value=False,
                                help="Calls Binance to score the current universe (~10s).")
    scanner_universe = st.slider("Scanner universe", 10, 50, 25, step=5)
    scanner_top_n = st.slider("Top-N display", 5, 25, 10, step=1)
    st.markdown("---")
    dash_cfg = load_dash_config()
    starting_cash = st.number_input(
        "Money you put in (USDT)",
        value=float(dash_cfg.get("starting_cash", 10_000.0)),
        step=100.0,
    )
    if starting_cash != dash_cfg.get("starting_cash"):
        save_dash_config({**dash_cfg, "starting_cash": starting_cash})


# ---------- Header ----------
state = load_state()
holdings = state.get("holdings", {})
last_reb = state.get("last_rebalance")
cash, equity, pos_values = current_equity(holdings)
pnl_usd = equity - starting_cash
pnl_pct = (equity / starting_cash - 1) * 100 if starting_cash > 0 else 0.0
hist = load_equity_history()
btc_now = float(fetch_ticker("BTC/USDT")["last"])
btc_at_start = float(hist["btc_price"].iloc[0]) if len(hist) and hist["btc_price"].iloc[0] > 0 else btc_now
btc_return_pct = (btc_now / btc_at_start - 1) * 100

mins_since = None
status_class, status_text = "pill-stale", "Unknown"
dot_animation = ""
if last_reb:
    mins_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last_reb)).total_seconds() / 60
    if mins_since < 60 * 25:
        status_class, status_text = "pill-healthy", "Healthy"
        dot_animation = "pulse-green"
    elif mins_since < 60 * 48:
        status_class, status_text = "pill-late", "Late"
    else:
        status_class, status_text = "pill-stale", "Stale"

dot_color = {"pill-healthy": GREEN, "pill-late": AMBER, "pill-stale": RED}[status_class]
mode_text = "Live" if is_live() else "Testnet"

st.markdown(
    f"""
    <div class="topbar">
      <div class="brand">
        <span class="brand-mark">◐ Rotation</span>
        <span class="brand-meta">· {datetime.now().strftime('%a %d %b · %H:%M')}</span>
      </div>
      <div style="display:flex; gap:8px; align-items:center;">
        <span class="pill pill-mode">{mode_text}</span>
        <span class="pill {status_class}">
          <span class="dot {dot_animation}" style="background:{dot_color};"></span>
          {status_text}{f" · {mins_since:.0f}m" if mins_since is not None and mins_since < 60 else f" · {mins_since/60:.1f}h" if mins_since else ""}
        </span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------- Hero P&L card ----------
pnl_color = GREEN if pnl_usd >= 0 else RED
pnl_sign = "+" if pnl_usd >= 0 else "−"
pnl_label = "Profit" if pnl_usd >= 0 else "Loss"

st.markdown(
    f"""
    <div class="hero">
      <div class="hero-grid">
        <div>
          <div class="hero-label">You put in</div>
          <div class="hero-value">${starting_cash:,.2f}</div>
        </div>
        <div>
          <div class="hero-label">Current value</div>
          <div class="hero-value">${equity:,.2f}</div>
        </div>
        <div class="hero-divider">
          <div class="hero-label">{pnl_label}</div>
          <div class="hero-pnl" style="color:{pnl_color};">{pnl_sign}${abs(pnl_usd):,.2f}</div>
          <div class="hero-pnl-pct" style="color:{pnl_color};">{pnl_sign}{abs(pnl_pct):.2f}%</div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------- Secondary metrics ----------
edge = pnl_pct - btc_return_pct
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("vs BTC HODL", f"{edge:+.2f}%",
              help=f"You: {pnl_pct:+.2f}% · BTC: {btc_return_pct:+.2f}%")
with k2:
    st.metric("Cash USDT", f"${cash:,.2f}")
with k3:
    st.metric("Positions", f"{len(holdings)}")
with k4:
    btc_short = f"${btc_now:,.0f}" if btc_now > 100 else f"${btc_now:,.2f}"
    st.metric("BTC price", btc_short)


# ---------- Equity chart + portfolio donut ----------
left, right = st.columns([2, 1])

PLOT_FONT = {"color": INK, "family": "Inter, system-ui"}
PLOT_LAYOUT = dict(
    paper_bgcolor=CARD,
    plot_bgcolor=CARD,
    font=PLOT_FONT,
    margin={"l": 8, "r": 8, "t": 12, "b": 8},
)

with left:
    st.markdown("## Equity over time")
    if len(hist) == 0:
        st.info("No equity history yet. The bot will log a snapshot at each rebalance.")
    else:
        plot_df = hist.copy()
        plot_df["btc_benchmark"] = starting_cash * (plot_df["btc_price"] / plot_df["btc_price"].iloc[0])
        now_row = pd.DataFrame([{
            "timestamp": datetime.now(timezone.utc),
            "equity": equity,
            "btc_benchmark": starting_cash * (btc_now / plot_df["btc_price"].iloc[0]),
        }])
        plot_df = pd.concat([plot_df, now_row], ignore_index=True)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=plot_df["timestamp"], y=plot_df["equity"],
            name="Strategy", mode="lines",
            line={"color": INK, "width": 2.2, "shape": "spline"},
            fill="tozeroy",
            fillcolor="rgba(15,23,42,0.04)",
            hovertemplate="%{x|%a %d %b %H:%M}<br><b>$%{y:,.2f}</b><extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=plot_df["timestamp"], y=plot_df["btc_benchmark"],
            name="BTC HODL", mode="lines",
            line={"color": SUBTLE, "width": 1.4, "dash": "dot"},
            hovertemplate="%{x|%a %d %b %H:%M}<br><b>$%{y:,.2f}</b><extra></extra>",
        ))
        fig.add_hline(y=starting_cash, line_dash="dash", line_color=HAIR,
                      annotation_text=f"start", annotation_position="right",
                      annotation_font={"size": 10, "color": SUBTLE})

        ymin = min(plot_df["equity"].min(), plot_df["btc_benchmark"].min(), starting_cash) * 0.97
        ymax = max(plot_df["equity"].max(), plot_df["btc_benchmark"].max(), starting_cash) * 1.03
        fig.update_layout(
            height=360, hovermode="x unified",
            yaxis={"title": None, "gridcolor": HAIR, "tickprefix": "$", "tickformat": ",.0f",
                   "range": [ymin, ymax], "showgrid": True, "zeroline": False},
            xaxis={"title": None, "showgrid": False, "tickformat": "%d %b"},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0,
                    "bgcolor": "rgba(0,0,0,0)", "font": {"size": 11, "color": MUTED}},
            **PLOT_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with right:
    st.markdown("## Portfolio mix")
    if not holdings and cash <= 0:
        st.info("No positions yet.")
    else:
        # Monochrome palette with subtle variation
        mono_palette = ["#0f172a", "#334155", "#475569", "#64748b", "#94a3b8", "#cbd5e1"]
        labels, values, colors = [], [], []
        for i, (sym, value) in enumerate(sorted(pos_values.items(), key=lambda x: -x[1])):
            labels.append(sym.replace("/USDT", ""))
            values.append(value)
            colors.append(mono_palette[i % len(mono_palette)])
        if cash > 0.5:
            labels.append("Cash")
            values.append(cash)
            colors.append("#e2e8f0")

        fig = go.Figure(data=[go.Pie(
            labels=labels, values=values, hole=0.7,
            marker={"colors": colors, "line": {"color": CARD, "width": 2}},
            textinfo="label",
            textfont={"color": INK, "size": 11},
            outsidetextfont={"color": INK, "size": 11},
            hovertemplate="<b>%{label}</b><br>$%{value:,.2f} · %{percent}<extra></extra>",
            sort=False,
        )])
        fig.add_annotation(
            text=f"<span style='font-size:1.2em; color:{INK}; font-weight:600'>${equity:,.0f}</span>"
                 f"<br><span style='font-size:0.75em; color:{MUTED}'>total</span>",
            showarrow=False,
        )
        fig.update_layout(height=360, showlegend=False, **PLOT_LAYOUT)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------- Holdings table ----------
st.markdown("## Holdings")
if not holdings:
    st.info("No open positions. The bot will buy on the next rebalance.")
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
        pnl_pct_coin = (current / entry - 1) * 100 if entry > 0 else 0
        pnl_usd_coin = value - units * entry
        rows.append({
            "Symbol": sym.replace("/USDT", ""),
            "Units": units,
            "Entry": entry,
            "Current": current,
            "P&L %": pnl_pct_coin,
            "P&L $": pnl_usd_coin,
            "Value": value,
            "Weight": value / equity * 100 if equity > 0 else 0,
        })
    df = pd.DataFrame(rows).sort_values("Value", ascending=False)
    pnl_min = float(df["P&L %"].min()) - 5
    pnl_max = float(df["P&L %"].max()) + 5

    st.dataframe(
        df,
        column_config={
            "Symbol": st.column_config.TextColumn(width="small"),
            "Units": st.column_config.NumberColumn(format="%.4f"),
            "Entry": st.column_config.NumberColumn(format="$%.4f"),
            "Current": st.column_config.NumberColumn(format="$%.4f"),
            "P&L %": st.column_config.ProgressColumn(
                "P&L %", format="%+.2f%%",
                min_value=pnl_min, max_value=pnl_max,
            ),
            "P&L $": st.column_config.NumberColumn(format="$%+,.2f"),
            "Value": st.column_config.NumberColumn(format="$%,.2f"),
            "Weight": st.column_config.ProgressColumn(
                "Weight", format="%.1f%%",
                min_value=0, max_value=100,
            ),
        },
        use_container_width=True, hide_index=True,
    )


# ---------- Live scanner ----------
st.markdown("## What the scanner sees")
if show_scanner:
    with st.spinner(f"Scanning top {scanner_universe} USDT pairs..."):
        try:
            universe = get_universe(data_exchange, top_n=scanner_universe, min_volume_usd=5_000_000)
            scan_df = scan(data_exchange, universe, timeframe="4h", days=14, momentum_lookback=60)
            if len(scan_df):
                trade_exchange.load_markets()
                tradeable = set(trade_exchange.symbols)
                scan_df["tradeable"] = scan_df["symbol"].isin(tradeable)
                held = set(holdings.keys())
                scan_df["currently_held"] = scan_df["symbol"].isin(held)
                scan_df["symbol"] = scan_df["symbol"].str.replace("/USDT", "")
                cols = ["symbol", "currently_held", "tradeable", "momentum_pct",
                        "above_long_pct", "atr_pct", "change_24h_pct", "quote_volume_m"]
                st.dataframe(
                    scan_df[cols].head(scanner_top_n),
                    column_config={
                        "symbol": "Symbol",
                        "currently_held": st.column_config.CheckboxColumn("Held"),
                        "tradeable": st.column_config.CheckboxColumn("Tradeable"),
                        "momentum_pct": st.column_config.ProgressColumn(
                            "Momentum", format="%+.1f%%",
                            min_value=0, max_value=float(scan_df["momentum_pct"].max()),
                        ),
                        "above_long_pct": st.column_config.NumberColumn("Above EMA", format="%+.1f%%"),
                        "atr_pct": st.column_config.NumberColumn("ATR", format="%.1f%%"),
                        "change_24h_pct": st.column_config.NumberColumn("24h", format="%+.1f%%"),
                        "quote_volume_m": st.column_config.NumberColumn("Vol", format="$%.0fM"),
                    },
                    use_container_width=True, hide_index=True,
                )
            else:
                st.warning("No coins passed the trend filter right now.")
        except Exception as e:
            st.error(f"Scanner failed: {e}")
else:
    st.caption("Toggle 'Run live scanner' in the sidebar.")


# ---------- Rebalance history ----------
st.markdown("## Recent rebalances")
if len(hist) == 0:
    st.info("No rebalances logged yet.")
else:
    display = hist.copy().tail(20).iloc[::-1]
    display["timestamp"] = display["timestamp"].dt.strftime("%a %d %b %H:%M")
    display["return%"] = (display["equity"] / starting_cash - 1) * 100
    display = display.rename(columns={
        "timestamp": "When", "equity": "Equity", "cash": "Cash",
        "n_positions": "Pos", "holdings": "Symbols",
    })
    display["Symbols"] = display["Symbols"].str.replace("/USDT", "").str.replace("|", " · ")
    ret_min = float(display["return%"].min()) - 5
    ret_max = float(display["return%"].max()) + 5
    st.dataframe(
        display[["When", "Equity", "Cash", "Pos", "return%", "Symbols"]],
        column_config={
            "Equity": st.column_config.NumberColumn(format="$%,.2f"),
            "Cash": st.column_config.NumberColumn(format="$%,.2f"),
            "return%": st.column_config.ProgressColumn(
                "Return", format="%+.2f%%",
                min_value=ret_min, max_value=ret_max,
            ),
        },
        use_container_width=True, hide_index=True,
    )


# ---------- Footer ----------
st.markdown(
    f"""<div class="footer">
      State: <code>{STATE_PATH.relative_to(ROOT)}</code> ·
      Equity log: <code>{EQUITY_LOG_PATH.relative_to(ROOT)}</code> ·
      Bot: <code>python -m src.rotation_bot</code>
    </div>""",
    unsafe_allow_html=True,
)

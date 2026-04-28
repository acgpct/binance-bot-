"""Binance connection wrapper. Defaults to testnet — set BINANCE_LIVE=true to use real funds."""

import os
from pathlib import Path

import ccxt
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_exchange() -> ccxt.binance:
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    live = os.getenv("BINANCE_LIVE", "false").lower() == "true"

    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing BINANCE_API_KEY / BINANCE_API_SECRET. "
            "Copy .env.example to .env and fill in testnet keys from "
            "https://testnet.binance.vision/"
        )

    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })

    if not live:
        exchange.set_sandbox_mode(True)

    return exchange


def is_live() -> bool:
    return os.getenv("BINANCE_LIVE", "false").lower() == "true"


def get_data_exchange() -> ccxt.binance:
    """Public, unauthenticated mainnet client — used for scanning & backtesting.

    Binance Spot Testnet only retains ~25 days of intraday history and a small
    subset of pairs. For a multi-coin scanner, we read market data from mainnet
    (no API key needed for public endpoints) and only route orders through the
    authenticated testnet client.
    """
    return ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })

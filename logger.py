"""
logger.py — 로그 + 거래 기록 모듈
- trader.log : 실행 로그
- trades.csv : 매매 내역 (매수/매도/손절/분할익절/트레일링)
"""
import logging
import csv
import os
from datetime import datetime
import config


def get_logger(name: str) -> logging.Logger:
    """파일 + 콘솔 동시 출력 로거"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    formatter.converter = lambda *_: datetime.now(config.KST).timetuple()
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger


# ── CSV 거래 기록 ──────────────────────────────────────

TRADE_HEADERS = [
    "날짜시간", "종류", "티커",
    "매수가(원)", "매도가(원)", "수량",
    "매수금액(원)", "매도금액(원)",
    "손익(원)", "손익률(%)",
    "사유", "MA20", "MA50", "MA200", "RSI", "ATR", "손절가",
]


def _ensure_csv():
    if not os.path.exists(config.TRADES_FILE):
        with open(config.TRADES_FILE, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=TRADE_HEADERS).writeheader()


def _fmt(v, default="-"):
    if v is None or v == "":
        return default
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def record_buy(ticker: str, price: float, volume: float, amount_krw: float, reason: str,
               ma20: float = 0, ma50: float = 0, ma200: float = 0,
               rsi: float = 0, atr: float = 0, stop_loss: float = 0):
    _ensure_csv()
    row = {
        "날짜시간":     datetime.now(config.KST).strftime("%Y-%m-%d %H:%M"),
        "종류":         "매수",
        "티커":         ticker,
        "매수가(원)":   _fmt(price),
        "매도가(원)":   "-",
        "수량":         f"{volume:.8f}",
        "매수금액(원)": _fmt(amount_krw),
        "매도금액(원)": "-",
        "손익(원)":     "-",
        "손익률(%)":    "-",
        "사유":         reason,
        "MA20":         _fmt(ma20),
        "MA50":         _fmt(ma50),
        "MA200":        _fmt(ma200),
        "RSI":          f"{rsi:.1f}",
        "ATR":          _fmt(atr),
        "손절가":       _fmt(stop_loss),
    }
    with open(config.TRADES_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=TRADE_HEADERS).writerow(row)


def record_sell(ticker: str, buy_price: float, sell_price: float,
                volume: float, buy_amount: float, sell_amount: float,
                pnl: float, pnl_pct: float, reason: str,
                ma20: float = 0, ma50: float = 0, ma200: float = 0,
                rsi: float = 0, atr: float = 0):
    _ensure_csv()
    sign = "+" if pnl >= 0 else ""
    row = {
        "날짜시간":     datetime.now(config.KST).strftime("%Y-%m-%d %H:%M"),
        "종류":         "매도",
        "티커":         ticker,
        "매수가(원)":   _fmt(buy_price),
        "매도가(원)":   _fmt(sell_price),
        "수량":         f"{volume:.8f}",
        "매수금액(원)": _fmt(buy_amount),
        "매도금액(원)": _fmt(sell_amount),
        "손익(원)":     f"{sign}{pnl:,.0f}",
        "손익률(%)":    f"{sign}{pnl_pct*100:.2f}%",
        "사유":         reason,
        "MA20":         _fmt(ma20),
        "MA50":         _fmt(ma50),
        "MA200":        _fmt(ma200),
        "RSI":          f"{rsi:.1f}",
        "ATR":          _fmt(atr),
        "손절가":       "-",
    }
    with open(config.TRADES_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=TRADE_HEADERS).writerow(row)

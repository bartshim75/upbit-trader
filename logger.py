"""
logger.py — 로그 + 거래 기록 모듈
- trader.log: 실행 로그
- trades.csv: 매매 내역 (매수가/매도가/손익 등 전체 기록)
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
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 콘솔 출력
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 파일 출력
    fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


# ── CSV 거래 기록 ──────────────────────────────────────────

TRADE_HEADERS = [
    "날짜시간", "종류", "티커",
    "매수가(원)", "매도가(원)", "수량(BTC)",
    "매수금액(원)", "매도금액(원)",
    "손익(원)", "손익률(%)",
    "사유", "MA단기", "MA장기", "RSI"
]


def _ensure_csv():
    """trades.csv 없으면 헤더 포함하여 생성"""
    if not os.path.exists(config.TRADES_FILE):
        with open(config.TRADES_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_HEADERS)
            writer.writeheader()


def record_buy(ticker: str, price: float, volume: float,
               amount_krw: float, reason: str,
               ma_short: float = 0, ma_long: float = 0, rsi: float = 0):
    """매수 기록"""
    _ensure_csv()
    row = {
        "날짜시간":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "종류":        "매수",
        "티커":        ticker,
        "매수가(원)":  f"{price:,.0f}",
        "매도가(원)":  "-",
        "수량(BTC)":   f"{volume:.8f}",
        "매수금액(원)": f"{amount_krw:,.0f}",
        "매도금액(원)": "-",
        "손익(원)":    "-",
        "손익률(%)":   "-",
        "사유":        reason,
        "MA단기":      f"{ma_short:,.0f}",
        "MA장기":      f"{ma_long:,.0f}",
        "RSI":         f"{rsi:.1f}",
    }
    with open(config.TRADES_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=TRADE_HEADERS).writerow(row)


def record_sell(ticker: str, buy_price: float, sell_price: float,
                volume: float, buy_amount: float, sell_amount: float,
                pnl: float, pnl_pct: float, reason: str,
                ma_short: float = 0, ma_long: float = 0, rsi: float = 0):
    """매도 기록"""
    _ensure_csv()
    pnl_sign = "+" if pnl >= 0 else ""
    row = {
        "날짜시간":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "종류":        "매도",
        "티커":        ticker,
        "매수가(원)":  f"{buy_price:,.0f}",
        "매도가(원)":  f"{sell_price:,.0f}",
        "수량(BTC)":   f"{volume:.8f}",
        "매수금액(원)": f"{buy_amount:,.0f}",
        "매도금액(원)": f"{sell_amount:,.0f}",
        "손익(원)":    f"{pnl_sign}{pnl:,.0f}",
        "손익률(%)":   f"{pnl_sign}{pnl_pct*100:.2f}%",
        "사유":        reason,
        "MA단기":      f"{ma_short:,.0f}",
        "MA장기":      f"{ma_long:,.0f}",
        "RSI":         f"{rsi:.1f}",
    }
    with open(config.TRADES_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=TRADE_HEADERS).writerow(row)

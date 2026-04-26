"""
upbit_api.py — 업비트 REST API 통신 모듈
pyupbit 라이브러리를 래핑하여 에러 처리를 강화합니다.
"""
import time
import pyupbit
import pandas as pd
import config
from logger import get_logger

log = get_logger(__name__)


def get_upbit_client():
    """인증된 업비트 클라이언트 반환"""
    return pyupbit.Upbit(config.UPBIT_ACCESS_KEY, config.UPBIT_SECRET_KEY)


def get_ohlcv(ticker: str, interval: str = "minute60", count: int = 100) -> pd.DataFrame:
    """
    OHLCV 캔들 데이터 조회
    interval: minute1 / minute60 / day / week
    """
    for attempt in range(3):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is not None and len(df) >= 30:
                return df
        except Exception as e:
            log.warning(f"캔들 조회 실패 ({attempt+1}/3): {e}")
            time.sleep(2)
    log.error("캔들 데이터 조회 최종 실패")
    return pd.DataFrame()


def get_current_price(ticker: str) -> float:
    """현재가 조회"""
    for attempt in range(3):
        try:
            price = pyupbit.get_current_price(ticker)
            if price:
                return float(price)
        except Exception as e:
            log.warning(f"현재가 조회 실패 ({attempt+1}/3): {e}")
            time.sleep(1)
    return 0.0


def get_krw_balance(upbit) -> float:
    """KRW 잔고 조회"""
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b["currency"] == "KRW":
                return float(b["balance"])
    except Exception as e:
        log.error(f"KRW 잔고 조회 실패: {e}")
    return 0.0


def get_coin_balance(upbit, ticker: str) -> dict:
    """
    코인 보유량 조회
    반환: {"balance": 수량, "avg_buy_price": 평균매수가}
    """
    currency = ticker.split("-")[1]  # KRW-BTC → BTC
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b["currency"] == currency:
                return {
                    "balance": float(b["balance"]),
                    "avg_buy_price": float(b["avg_buy_price"])
                }
    except Exception as e:
        log.error(f"코인 잔고 조회 실패: {e}")
    return {"balance": 0.0, "avg_buy_price": 0.0}


def buy_market_order(upbit, ticker: str, amount_krw: float) -> dict | None:
    """
    시장가 매수
    amount_krw: 매수할 금액 (원)
    """
    try:
        result = upbit.buy_market_order(ticker, amount_krw)
        log.info(f"매수 주문 완료: {ticker} {amount_krw:,.0f}원 | 결과: {result}")
        return result
    except Exception as e:
        log.error(f"매수 주문 실패: {e}")
        return None


def sell_market_order(upbit, ticker: str, volume: float) -> dict | None:
    """
    시장가 매도
    volume: 매도할 코인 수량
    """
    try:
        result = upbit.sell_market_order(ticker, volume)
        log.info(f"매도 주문 완료: {ticker} {volume} | 결과: {result}")
        return result
    except Exception as e:
        log.error(f"매도 주문 실패: {e}")
        return None

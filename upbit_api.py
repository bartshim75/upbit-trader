"""
upbit_api.py — 업비트 REST API 통신 모듈
pyupbit 라이브러리를 래핑하여 에러 처리 / 재시도 / 슬리피지 검사를 강화합니다.
"""
import time
from typing import Optional
import requests
import pyupbit
import pandas as pd
import config
from logger import get_logger

log = get_logger(__name__)

_ORIGINAL_REQUEST = requests.sessions.Session.request


def _request_with_default_timeout(self, method, url, **kwargs):
    """pyupbit 내부 requests 호출이 무기한 대기하지 않도록 기본 timeout 적용."""
    if kwargs.get("timeout") is None:
        kwargs["timeout"] = config.API_TIMEOUT_SEC
    return _ORIGINAL_REQUEST(self, method, url, **kwargs)


requests.sessions.Session.request = _request_with_default_timeout


def get_upbit_client():
    """인증된 업비트 클라이언트 반환"""
    return pyupbit.Upbit(config.UPBIT_ACCESS_KEY, config.UPBIT_SECRET_KEY)


def get_ohlcv(ticker: str, interval: str = "minute60", count: int = 250) -> pd.DataFrame:
    """OHLCV 캔들 데이터 조회 (재시도 3회)"""
    for attempt in range(3):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is not None and len(df) >= 30:
                return df
            rows = 0 if df is None else len(df)
            log.warning(f"캔들 조회 데이터 부족 ({attempt+1}/3): {ticker} rows={rows}")
        except Exception as e:
            log.warning(f"캔들 조회 실패 ({attempt+1}/3): {ticker} {type(e).__name__}: {e}")
        time.sleep(2)
    log.error(f"캔들 데이터 조회 최종 실패: {ticker}")
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


def get_orderbook(ticker: str) -> Optional[dict]:
    """호가 조회 (슬리피지 체크용)"""
    for attempt in range(3):
        try:
            ob = pyupbit.get_orderbook(ticker)
            # pyupbit 버전에 따라 list 또는 dict 반환
            if isinstance(ob, list) and ob:
                return ob[0]
            if isinstance(ob, dict):
                return ob
        except Exception as e:
            log.warning(f"호가 조회 실패 ({attempt+1}/3): {e}")
            time.sleep(1)
    return None


def estimate_slippage(ticker: str, side: str, ref_price: float) -> Optional[float]:
    """
    side='BUY'  → 1호가 매도호가 / ref_price - 1
    side='SELL' → 1 - 1호가 매수호가 / ref_price
    체결가가 ref_price 대비 얼마나 불리한지(양수%) 추정.
    호가 조회 실패 시 None.
    """
    ob = get_orderbook(ticker)
    if not ob or "orderbook_units" not in ob or not ob["orderbook_units"]:
        return None
    top = ob["orderbook_units"][0]
    try:
        if side == "BUY":
            ask = float(top["ask_price"])
            return (ask - ref_price) / ref_price
        else:
            bid = float(top["bid_price"])
            return (ref_price - bid) / ref_price
    except (KeyError, TypeError, ValueError):
        return None


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


def get_coin_balance(upbit, ticker: str) -> Optional[dict]:
    """
    코인 보유량 조회 → {"balance": 수량, "avg_buy_price": 평균매수가}.

    정상 응답에 해당 통화가 없으면 실제 미보유이므로 0을 반환한다.
    API 오류는 실제 0과 구분할 수 있도록 3회 재시도 후 None을 반환한다.
    """
    currency = ticker.split("-")[1]
    for attempt in range(3):
        try:
            balances = upbit.get_balances()
            if not isinstance(balances, list):
                raise ValueError(f"예상하지 못한 잔고 응답 형식: {type(balances).__name__}")
            for b in balances:
                if b.get("currency") == currency:
                    return {
                        "balance": float(b.get("balance", 0)),
                        "avg_buy_price": float(b.get("avg_buy_price", 0)),
                    }
            return {"balance": 0.0, "avg_buy_price": 0.0}
        except Exception as e:
            log.warning(f"코인 잔고 조회 실패 ({attempt+1}/3): {ticker} {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(1)
    log.error(f"코인 잔고 조회 최종 실패: {ticker} — 실제 0으로 간주하지 않고 상태 변경을 중단합니다")
    return None


def buy_market_order(upbit, ticker: str, amount_krw: float) -> Optional[dict]:
    """시장가 매수"""
    try:
        result = upbit.buy_market_order(ticker, amount_krw)
        log.info(f"매수 주문 전송: {ticker} {amount_krw:,.0f}원 | 결과: {result}")
        return result
    except Exception as e:
        log.error(f"매수 주문 실패: {e}")
        return None


def sell_market_order(upbit, ticker: str, volume: float) -> Optional[dict]:
    """시장가 매도"""
    try:
        result = upbit.sell_market_order(ticker, volume)
        log.info(f"매도 주문 전송: {ticker} {volume} | 결과: {result}")
        return result
    except Exception as e:
        log.error(f"매도 주문 실패: {e}")
        return None


def get_order(upbit, uuid: str) -> Optional[dict]:
    """주문 상태 조회 (체결 확인용)"""
    try:
        return upbit.get_order(uuid)
    except Exception as e:
        log.warning(f"주문 조회 실패 (uuid={uuid}): {e}")
        return None


def wait_for_fill(upbit, uuid: str, timeout_sec: float = 5.0) -> Optional[dict]:
    """
    주문 체결 폴링 (시장가 주문은 보통 즉시 체결).
    체결되면 주문 정보, 미체결/실패 시 None.
    """
    deadline = time.time() + timeout_sec
    last = None
    while time.time() < deadline:
        last = get_order(upbit, uuid)
        if last and last.get("state") in ("done", "cancel"):
            return last
        time.sleep(0.4)
    log.warning(f"주문 체결 대기 시간 초과 (uuid={uuid}): last={last}")
    return last


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize_order_fill(order: Optional[dict]) -> dict:
    """
    주문 조회 응답에서 실제 체결 수량/금액을 추출.
    시장가 주문은 done/cancel 어느 상태에서도 체결분이 있을 수 있으므로
    state보다 executed_volume/executed_funds를 우선 신뢰한다.
    """
    summary = {
        "state": "",
        "executed_volume": 0.0,
        "executed_funds": 0.0,
        "avg_price": 0.0,
        "paid_fee": 0.0,
        "trades_count": 0,
    }
    if not isinstance(order, dict):
        return summary

    summary["state"] = str(order.get("state") or "")
    summary["executed_volume"] = _to_float(order.get("executed_volume"))
    summary["executed_funds"] = _to_float(order.get("executed_funds"))
    summary["paid_fee"] = _to_float(order.get("paid_fee"))
    summary["trades_count"] = int(_to_float(order.get("trades_count"), 0.0))

    trades = order.get("trades")
    if isinstance(trades, list) and trades:
        trade_volume = 0.0
        trade_funds = 0.0
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            volume = _to_float(trade.get("volume"))
            funds = _to_float(trade.get("funds"))
            if funds <= 0:
                funds = _to_float(trade.get("price")) * volume
            trade_volume += volume
            trade_funds += funds

        if trade_volume > 0:
            summary["executed_volume"] = trade_volume
        if trade_funds > 0:
            summary["executed_funds"] = trade_funds

    if summary["executed_volume"] > 0 and summary["executed_funds"] > 0:
        summary["avg_price"] = summary["executed_funds"] / summary["executed_volume"]

    return summary

"""
trader.py — 매수/매도 실행 및 포지션 관리
"""
import time
import config
import upbit_api as api
import strategy
import logger as rec
from budget_manager import BudgetManager
from logger import get_logger

log = get_logger(__name__)


def run_trade_cycle(budget: BudgetManager):
    """
    1회 매매 사이클 실행 (1시간마다 호출)
    1. 현재 포지션 점검 → 손절/익절/데드크로스 매도
    2. 신규 매수 신호 확인 → 골든크로스 매수
    """
    upbit  = api.get_upbit_client()
    ticker = config.TICKER

    log.info(f"━━━ 매매 사이클 시작: {ticker} ━━━")

    # ── 캔들 데이터 및 지표 계산 ─────────────────────────
    df = api.get_ohlcv(ticker, interval="minute60", count=config.CANDLE_COUNT)
    if df.empty:
        log.error("캔들 데이터 없음 — 이번 사이클 스킵")
        return

    signal_info = strategy.get_signal(df)
    current_price = api.get_current_price(ticker)
    if current_price <= 0:
        log.error("현재가 조회 실패 — 이번 사이클 스킵")
        return

    log.info(f"현재가: {current_price:,.0f}원 | 신호: {signal_info['signal']} | {signal_info['reason']}")

    # ── STEP 1: 보유 포지션 점검 ────────────────────────
    coin_info = api.get_coin_balance(upbit, ticker)
    volume      = coin_info["balance"]
    avg_buy_price = coin_info["avg_buy_price"]

    if volume > 0 and avg_buy_price > 0:
        # 손절/익절 체크
        st = strategy.check_stop_take(avg_buy_price, current_price)
        sell_reason = None

        if st["action"] == "STOP_LOSS":
            sell_reason = "STOP_LOSS"
            log.warning(f"🛑 손절 실행: 매수가={avg_buy_price:,.0f} 현재가={current_price:,.0f} ({st['pnl_pct']*100:.2f}%)")

        elif st["action"] == "TAKE_PROFIT":
            sell_reason = "TAKE_PROFIT"
            log.info(f"🎯 익절 실행: 매수가={avg_buy_price:,.0f} 현재가={current_price:,.0f} ({st['pnl_pct']*100:.2f}%)")

        elif signal_info["signal"] == "SELL":
            sell_reason = "DEAD_CROSS"
            log.info(f"📉 데드크로스 매도 실행")

        if sell_reason:
            _execute_sell(upbit, ticker, volume, avg_buy_price, current_price, sell_reason, signal_info, budget)
            time.sleep(1)  # 주문 처리 대기

    # ── STEP 2: 신규 매수 판단 ──────────────────────────
    krw_balance = api.get_krw_balance(upbit)

    if signal_info["signal"] == "BUY":
        if budget.can_buy(krw_balance):
            _execute_buy(upbit, ticker, current_price, signal_info, budget)
        else:
            log.info("매수 신호 있으나 예산/잔고 부족으로 스킵")
    else:
        log.info(f"매수 신호 없음 — 대기")

    # ── 현황 출력 ────────────────────────────────────────
    budget.print_status()
    log.info(f"━━━ 매매 사이클 종료 ━━━\n")


def _execute_buy(upbit, ticker: str, current_price: float,
                 signal_info: dict, budget: BudgetManager):
    """매수 실행"""
    amount = config.ORDER_AMOUNT
    log.info(f"💰 매수 시도: {amount:,.0f}원")

    result = api.buy_market_order(upbit, ticker, amount)
    if not result:
        log.error("매수 주문 실패")
        return

    time.sleep(0.5)  # 체결 대기
    # 실제 체결 수량 확인
    coin_info = api.get_coin_balance(upbit, ticker)
    volume = coin_info["balance"]
    exec_price = coin_info["avg_buy_price"] or current_price

    budget.record_buy(amount)
    rec.record_buy(
        ticker=ticker,
        price=exec_price,
        volume=volume,
        amount_krw=amount,
        reason=signal_info["reason"],
        ma_short=signal_info["ma_short"],
        ma_long=signal_info["ma_long"],
        rsi=signal_info["rsi"],
    )
    log.info(f"✅ 매수 완료: {exec_price:,.0f}원 × {volume:.8f}BTC = {amount:,.0f}원")


def _execute_sell(upbit, ticker: str, volume: float,
                  avg_buy_price: float, current_price: float,
                  reason: str, signal_info: dict, budget: BudgetManager):
    """매도 실행"""
    log.info(f"💸 매도 시도: {volume:.8f}BTC")

    result = api.sell_market_order(upbit, ticker, volume)
    if not result:
        log.error("매도 주문 실패")
        return

    time.sleep(0.5)  # 체결 대기

    # 손익 계산
    buy_amount  = avg_buy_price * volume
    sell_amount = current_price * volume
    pnl         = sell_amount - buy_amount
    pnl_pct     = (current_price - avg_buy_price) / avg_buy_price

    budget.record_sell(buy_amount, sell_amount, reason)
    rec.record_sell(
        ticker=ticker,
        buy_price=avg_buy_price,
        sell_price=current_price,
        volume=volume,
        buy_amount=buy_amount,
        sell_amount=sell_amount,
        pnl=pnl,
        pnl_pct=pnl_pct,
        reason=reason,
        ma_short=signal_info["ma_short"],
        ma_long=signal_info["ma_long"],
        rsi=signal_info["rsi"],
    )

    pnl_sign = "+" if pnl >= 0 else ""
    log.info(f"✅ 매도 완료: {current_price:,.0f}원 | 손익: {pnl_sign}{pnl:,.0f}원 ({pnl_sign}{pnl_pct*100:.2f}%) | 사유: {reason}")

"""
trader.py — 매매 사이클 (1시간마다 실행)

흐름:
  1) 캔들/지표 로드, 변동성 차단 체크
  2) 보유 포지션이 있으면 → 손절/TP1/TP2/트레일링/추세이탈 평가 → 부분 또는 전량 매도
  3) 무포지션이면 → 일일 차단 체크 → 매수 신호 평가 → 슬리피지 검사 후 진입
"""
import time
from datetime import datetime
import config
import upbit_api as api
import strategy
import logger as rec
from budget_manager import BudgetManager
from logger import get_logger

log = get_logger(__name__)


def run_trade_cycle(budget: BudgetManager):
    upbit  = api.get_upbit_client()
    ticker = config.TICKER
    log.info(f"━━━ 매매 사이클 시작: {ticker} ━━━")

    # ── 1) 시세 / 지표 ─────────────────────────────
    df = api.get_ohlcv(ticker, interval="minute60", count=config.CANDLE_COUNT)
    if df.empty:
        log.error("캔들 데이터 없음 — 사이클 스킵")
        return

    current_price = api.get_current_price(ticker)
    if current_price <= 0:
        log.error("현재가 조회 실패 — 사이클 스킵")
        return

    halt_vol = strategy.is_volatility_halt(df)
    if halt_vol:
        log.warning(f"⚠ 변동성 차단: {halt_vol} — 사이클 스킵")
        budget.print_status()
        return

    # ── 2) 포지션 동기화 ───────────────────────────
    coin_info     = api.get_coin_balance(upbit, ticker)
    exchange_vol  = coin_info["balance"]
    exchange_avg  = coin_info["avg_buy_price"]
    position      = budget.load_position()

    # 거래소엔 잔고 있는데 로컬 상태 없는 경우(재시작 등) → 보수적 초기화
    if exchange_vol > 0 and position is None and exchange_avg > 0:
        position = _bootstrap_position(df, exchange_vol, exchange_avg, current_price)
        budget.save_position(position)
        log.warning(f"⚠ 기존 보유 감지 → 포지션 상태 부트스트랩: 매수가={exchange_avg:,.0f}, 손절가={position['stop_loss_price']:,.0f}")

    # 거래소엔 없는데 로컬 상태 있는 경우(수동 매도 등) → 정리
    if exchange_vol <= 0 and position is not None:
        log.warning("⚠ 거래소 잔고 없음 → 로컬 포지션 상태 정리")
        budget.clear_position()
        position = None

    # ── 3) 매도 평가 ───────────────────────────────
    if position is not None and exchange_vol > 0:
        # 고점 갱신
        if current_price > position.get("highest_price", 0):
            position["highest_price"] = current_price
            budget.save_position(position)

        decision = strategy.evaluate_exit(position, current_price, df)
        log.info(f"현재가={current_price:,.0f} | 포지션평가: {decision['action']} | {decision['reason']}")

        if decision["action"] != "HOLD":
            _execute_sell(upbit, ticker, position, exchange_vol, current_price, decision, budget)
        else:
            # 보유만 갱신
            budget.print_status()
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    # ── 4) 매수 평가 ───────────────────────────────
    halt = budget.is_trading_halted()
    if halt:
        log.info(f"⛔ 신규 매수 차단: {halt}")
        budget.print_status()
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    sig = strategy.get_buy_signal(df, current_price)
    log.info(f"현재가={current_price:,.0f} | {sig['reason']}")

    if sig["signal"] != "BUY":
        budget.print_status()
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    krw = api.get_krw_balance(upbit)
    if not budget.can_buy(krw):
        budget.print_status()
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    # 슬리피지 검사
    slip = api.estimate_slippage(ticker, "BUY", current_price)
    if slip is not None and slip > config.SLIPPAGE_LIMIT_PCT:
        log.warning(f"⛔ 슬리피지 초과: {slip*100:+.2f}% > {config.SLIPPAGE_LIMIT_PCT*100:.2f}% — 매수 취소")
        budget.print_status()
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    _execute_buy(upbit, ticker, current_price, sig, budget)
    budget.print_status()
    log.info("━━━ 매매 사이클 종료 ━━━\n")


# ── 매수 ─────────────────────────────────────────────
def _execute_buy(upbit, ticker: str, current_price: float,
                 sig: dict, budget: BudgetManager):
    amount = budget.order_amount()
    log.info(f"💰 매수 시도: {amount:,.0f}원 (현재가 {current_price:,.0f})")

    result = api.buy_market_order(upbit, ticker, amount)
    if not result:
        log.error("매수 주문 실패 — 포지션 미생성")
        return

    # 체결 확인
    uuid = result.get("uuid") if isinstance(result, dict) else None
    if uuid:
        api.wait_for_fill(upbit, uuid, timeout_sec=5.0)
    else:
        time.sleep(0.8)

    coin_info = api.get_coin_balance(upbit, ticker)
    volume     = coin_info["balance"]
    exec_price = coin_info["avg_buy_price"] or current_price

    if volume <= 0:
        log.error("⚠ 매수 후 잔고 0 — 체결 실패로 간주, 포지션 미생성")
        return

    ind = sig["indicators"]
    entry_atr = float(ind.get("atr", 0))
    stop_loss_price = strategy.compute_stop_loss(exec_price, entry_atr)

    position = {
        "ticker":            ticker,
        "entry_price":       exec_price,
        "entry_time":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_volume":    volume,
        "remaining_volume":  volume,
        "entry_atr":         entry_atr,
        "stop_loss_price":   stop_loss_price,
        "highest_price":     max(exec_price, current_price),
        "tp1_done":          False,
        "tp2_done":          False,
    }
    budget.save_position(position)
    budget.record_buy(amount)

    rec.record_buy(
        ticker=ticker, price=exec_price, volume=volume, amount_krw=amount,
        reason=sig["reason"],
        ma20=ind.get("ma20", 0), ma50=ind.get("ma50", 0), ma200=ind.get("ma200", 0),
        rsi=ind.get("rsi", 0), atr=entry_atr,
        stop_loss=stop_loss_price,
    )
    log.info(f"✅ 매수 완료: {exec_price:,.0f}원 × {volume:.8f} = {amount:,.0f}원 | 손절가 {stop_loss_price:,.0f}")


# ── 매도 ─────────────────────────────────────────────
def _execute_sell(upbit, ticker: str, position: dict, exchange_vol: float,
                  current_price: float, decision: dict, budget: BudgetManager):
    action     = decision["action"]
    sell_ratio = decision["sell_ratio"]

    # TP1/TP2는 "초기 수량" 대비, 손절/트레일링/추세이탈은 잔량 전량
    if action in ("TP1", "TP2"):
        target_volume = position["initial_volume"] * sell_ratio
        # 잔량보다 크면 잔량으로 캡
        target_volume = min(target_volume, exchange_vol)
    else:
        target_volume = exchange_vol  # 전량

    if target_volume <= 0:
        log.warning(f"매도 수량 0 — 스킵 ({action})")
        return

    # 슬리피지 체크
    slip = api.estimate_slippage(ticker, "SELL", current_price)
    if slip is not None and slip > config.SLIPPAGE_LIMIT_PCT:
        # 손절/트레일링은 즉시 빠져나가야 하므로 슬리피지 무시
        if action in ("STOP_LOSS", "TRAILING_STOP", "TREND_BREAK"):
            log.warning(f"⚠ 슬리피지 {slip*100:+.2f}% 이지만 {action} → 강제 매도")
        else:
            log.warning(f"⛔ 슬리피지 초과: {slip*100:+.2f}% > {config.SLIPPAGE_LIMIT_PCT*100:.2f}% — {action} 매도 취소")
            return

    log.info(f"💸 매도 시도: {target_volume:.8f} ({action})")
    result = api.sell_market_order(upbit, ticker, target_volume)
    if not result:
        log.error(f"매도 주문 실패 ({action})")
        return

    uuid = result.get("uuid") if isinstance(result, dict) else None
    if uuid:
        api.wait_for_fill(upbit, uuid, timeout_sec=5.0)
    else:
        time.sleep(0.8)

    # 손익 계산 (체결가는 current_price로 근사)
    entry_price = position["entry_price"]
    sold_volume = target_volume
    buy_amount  = entry_price * sold_volume
    sell_amount = current_price * sold_volume
    pnl         = sell_amount - buy_amount
    pnl_pct     = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

    budget.record_sell(buy_amount, sell_amount, action)
    rec.record_sell(
        ticker=ticker, buy_price=entry_price, sell_price=current_price,
        volume=sold_volume, buy_amount=buy_amount, sell_amount=sell_amount,
        pnl=pnl, pnl_pct=pnl_pct, reason=action,
    )
    sign = "+" if pnl >= 0 else ""
    log.info(f"✅ {action} 완료: {current_price:,.0f}원 × {sold_volume:.8f} | 손익 {sign}{pnl:,.0f}원 ({sign}{pnl_pct*100:.2f}%)")

    # 포지션 갱신
    if action == "TP1":
        position["tp1_done"] = True
        position["remaining_volume"] = max(0.0, position["remaining_volume"] - sold_volume)
        # 손절가를 본전(매수가)으로 끌어올림 → 잔여 물량 손실 방지
        position["stop_loss_price"] = max(position["stop_loss_price"], entry_price)
        budget.save_position(position)
        log.info(f"  → TP1 후: 잔량 {position['remaining_volume']:.8f}, 손절가 본전 {entry_price:,.0f}으로 상향")
    elif action == "TP2":
        position["tp2_done"] = True
        position["remaining_volume"] = max(0.0, position["remaining_volume"] - sold_volume)
        budget.save_position(position)
        log.info(f"  → TP2 후: 잔량 {position['remaining_volume']:.8f} (트레일링 -{config.TRAILING_STOP_PCT*100:.1f}% 적용 중)")
    else:
        # 전량 매도 → 포지션 종료
        budget.clear_position()
        log.info("  → 포지션 종료")


# ── 재시작 시 포지션 부트스트랩 ─────────────────────
def _bootstrap_position(df, volume: float, avg_price: float, current_price: float) -> dict:
    """
    프로그램 재시작 등으로 로컬 position.json은 없는데 거래소엔 잔고가 있을 때.
    현재 ATR로 손절가만 보수적으로 계산. TP는 처음부터 다시 평가.
    """
    ind_df = strategy.calc_indicators(df)
    atr = float(ind_df["atr"].iloc[-1]) if not ind_df.empty else 0.0
    return {
        "ticker":            config.TICKER,
        "entry_price":       avg_price,
        "entry_time":        datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (bootstrap)",
        "initial_volume":    volume,
        "remaining_volume":  volume,
        "entry_atr":         atr,
        "stop_loss_price":   strategy.compute_stop_loss(avg_price, atr),
        "highest_price":     max(avg_price, current_price),
        "tp1_done":          False,
        "tp2_done":          False,
    }

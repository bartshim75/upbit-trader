"""
trader.py — 매매 사이클

두 가지 진입점:
  - run_trade_cycle: 매 정시(:00)에 호출. 매수/매도 모두 평가.
  - run_exit_check : 분 단위로 호출. 포지션 보유 시에만 손절/TP/트레일링 평가
                    (무포지션이면 즉시 리턴).

원칙:
  - 사용자가 봇 시작 전부터 보유하고 있던 BTC(=baseline)는 절대 건드리지 않음
  - 봇은 자기가 매수한 수량만 추적/매도
  - 부트스트랩 로직 없음 (재시작 시 기존 잔고를 자기 포지션으로 인식하지 않음)

run_trade_cycle 흐름:
  1) 캔들/지표 로드, 변동성 차단 체크
  2) baseline 보장 (없으면 현재 잔고로 기록)
  3) 봇 보유 포지션이 있으면 → 손절/TP1/TP2/트레일링/추세이탈 평가 → 부분/전량 매도
  4) 무포지션이면 → 일일 차단 체크 → 매수 신호 평가 → 슬리피지 검사 후 진입
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

    # ── 2) 잔고 / baseline ─────────────────────────
    coin_info     = api.get_coin_balance(upbit, ticker)
    exchange_vol  = coin_info["balance"]

    # 최초 1회: baseline 기록 (봇이 시작될 때의 사용자 기존 보유분)
    budget.ensure_baseline(exchange_vol)
    baseline_vol = budget.baseline_volume()
    bot_vol      = budget.bot_owned_volume(exchange_vol)

    log.info(f"잔고: 거래소={exchange_vol:.8f} | baseline(보호)={baseline_vol:.8f} | 봇운용={bot_vol:.8f}")

    # ── 3) 포지션 평가 / 매도 ──────────────────────
    position = budget.load_position()

    # 거래소 잔고가 baseline 이하면 봇 운용분이 없는 것 → 포지션 정리
    if bot_vol <= 0:
        if position is not None:
            log.warning("⚠ 거래소 잔고가 baseline 이하 → 봇 포지션 상태 정리")
            budget.clear_position()
            position = None

    if position is not None and bot_vol > 0:
        # 고점 갱신
        if current_price > position.get("highest_price", 0):
            position["highest_price"] = current_price
            budget.save_position(position)

        decision = strategy.evaluate_exit(position, current_price, df)
        log.info(f"현재가={current_price:,.0f} | 포지션평가: {decision['action']} | {decision['reason']}")

        if decision["action"] != "HOLD":
            _execute_sell(upbit, ticker, position, bot_vol, current_price, decision, budget)
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

    _execute_buy(upbit, ticker, current_price, sig, budget, exchange_vol)
    budget.print_status()
    log.info("━━━ 매매 사이클 종료 ━━━\n")


# ── 분 단위 exit 체크 ───────────────────────────────
def run_exit_check(budget: BudgetManager):
    """
    포지션 보유 중일 때만 손절/TP/트레일링/추세이탈을 분 단위로 평가.
    무포지션이면 즉시 리턴 (저렴 — 파일 한 번 읽고 끝).
    매수 평가는 절대 하지 않음 (매수는 정시 run_trade_cycle 전용).
    """
    position = budget.load_position()
    if position is None:
        return

    upbit  = api.get_upbit_client()
    ticker = config.TICKER

    current_price = api.get_current_price(ticker)
    if current_price <= 0:
        log.warning("[exit-check] 현재가 조회 실패 — 스킵")
        return

    coin_info    = api.get_coin_balance(upbit, ticker)
    exchange_vol = coin_info["balance"]
    bot_vol      = budget.bot_owned_volume(exchange_vol)

    if bot_vol <= 0:
        log.warning("[exit-check] 거래소 잔고 ≤ baseline → 봇 포지션 정리")
        budget.clear_position()
        return

    # 고점 갱신 (트레일링 스탑용)
    if current_price > position.get("highest_price", 0):
        position["highest_price"] = current_price
        budget.save_position(position)

    df = api.get_ohlcv(ticker, interval="minute60", count=config.CANDLE_COUNT)
    decision = strategy.evaluate_exit(position, current_price, df)

    if decision["action"] == "HOLD":
        return  # 평상시는 로그도 안 남김 (분 단위 호출이라 로그 폭증 방지)

    log.info(f"[exit-check] 현재가={current_price:,.0f} | {decision['action']} | {decision['reason']}")
    _execute_sell(upbit, ticker, position, bot_vol, current_price, decision, budget)
    budget.print_status()


# ── 매수 ─────────────────────────────────────────────
def _execute_buy(upbit, ticker: str, current_price: float,
                 sig: dict, budget: BudgetManager, exchange_vol_before: float):
    amount = budget.order_amount()
    log.info(f"💰 매수 시도: {amount:,.0f}원 (현재가 {current_price:,.0f})")

    result = api.buy_market_order(upbit, ticker, amount)
    if not result:
        log.error("매수 주문 실패 — 포지션 미생성")
        return

    uuid = result.get("uuid") if isinstance(result, dict) else None
    if uuid:
        api.wait_for_fill(upbit, uuid, timeout_sec=5.0)
    else:
        time.sleep(0.8)

    # 매수 후 잔고 → 신규 매수 수량 = (after - before)
    coin_info_after = api.get_coin_balance(upbit, ticker)
    exchange_vol_after = coin_info_after["balance"]
    volume_purchased = exchange_vol_after - exchange_vol_before

    if volume_purchased <= 0:
        log.error(f"⚠ 매수 후 잔고 변화 없음 (before={exchange_vol_before}, after={exchange_vol_after}) — 포지션 미생성")
        return

    # 봇이 산 평균 매수가 (수수료 무시 근사)
    exec_price = amount / volume_purchased

    ind = sig["indicators"]
    entry_atr = float(ind.get("atr", 0))
    stop_loss_price = strategy.compute_stop_loss(exec_price, entry_atr)

    position = {
        "ticker":            ticker,
        "entry_price":       exec_price,
        "entry_time":        datetime.now(config.KST).strftime("%Y-%m-%d %H:%M:%S"),
        "initial_volume":    volume_purchased,
        "remaining_volume":  volume_purchased,
        "entry_atr":         entry_atr,
        "stop_loss_price":   stop_loss_price,
        "highest_price":     max(exec_price, current_price),
        "tp1_done":          False,
        "tp2_done":          False,
    }
    budget.save_position(position)
    budget.record_buy(amount)

    rec.record_buy(
        ticker=ticker, price=exec_price, volume=volume_purchased, amount_krw=amount,
        reason=sig["reason"],
        ma20=ind.get("ma20", 0), ma50=ind.get("ma50", 0), ma200=ind.get("ma200", 0),
        rsi=ind.get("rsi", 0), atr=entry_atr,
        stop_loss=stop_loss_price,
    )
    log.info(f"✅ 매수 완료: {exec_price:,.0f}원 × {volume_purchased:.8f} = {amount:,.0f}원 | 손절가 {stop_loss_price:,.0f}")


# ── 매도 ─────────────────────────────────────────────
def _execute_sell(upbit, ticker: str, position: dict, bot_vol: float,
                  current_price: float, decision: dict, budget: BudgetManager):
    """
    매도 실행. bot_vol = 봇이 매도 가능한 최대 수량 (baseline 제외).
    어떤 경우에도 bot_vol을 초과해서 매도하지 않음 → 사용자 기존 자산 보호.
    """
    action     = decision["action"]
    sell_ratio = decision["sell_ratio"]

    # TP1/TP2는 "초기 수량" 대비, 손절/트레일링/추세이탈은 잔량 전량
    if action in ("TP1", "TP2"):
        target_volume = position["initial_volume"] * sell_ratio
    else:
        target_volume = position["remaining_volume"]

    # 안전 캡: bot_vol 초과 절대 금지
    safe_volume = min(target_volume, bot_vol)

    if safe_volume <= 0:
        log.warning(f"매도 수량 0 — 스킵 ({action})")
        return

    if safe_volume < target_volume:
        log.warning(f"⚠ 안전 캡 적용: 목표={target_volume:.8f} → 실제={safe_volume:.8f} (baseline 보호)")

    # 슬리피지 체크
    slip = api.estimate_slippage(ticker, "SELL", current_price)
    if slip is not None and slip > config.SLIPPAGE_LIMIT_PCT:
        if action in ("STOP_LOSS", "TRAILING_STOP", "TREND_BREAK"):
            log.warning(f"⚠ 슬리피지 {slip*100:+.2f}% 이지만 {action} → 강제 매도")
        else:
            log.warning(f"⛔ 슬리피지 초과: {slip*100:+.2f}% > {config.SLIPPAGE_LIMIT_PCT*100:.2f}% — {action} 매도 취소")
            return

    log.info(f"💸 매도 시도: {safe_volume:.8f} ({action})")
    result = api.sell_market_order(upbit, ticker, safe_volume)
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
    sold_volume = safe_volume
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
    position["remaining_volume"] = max(0.0, position["remaining_volume"] - sold_volume)

    if action == "TP1":
        position["tp1_done"] = True
        # 잔여물량 보호: 손절가를 본전(매수가)으로 상향
        position["stop_loss_price"] = max(position["stop_loss_price"], entry_price)
        budget.save_position(position)
        log.info(f"  → TP1 후: 잔량 {position['remaining_volume']:.8f}, 손절가 본전 {entry_price:,.0f}으로 상향")
    elif action == "TP2":
        position["tp2_done"] = True
        budget.save_position(position)
        log.info(f"  → TP2 후: 잔량 {position['remaining_volume']:.8f} (트레일링 -{config.TRAILING_STOP_PCT*100:.1f}% 적용 중)")
    else:
        # 전량 매도 → 포지션 종료
        budget.clear_position()
        log.info("  → 포지션 종료")

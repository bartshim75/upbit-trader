"""
trader.py — 매매 사이클

두 가지 진입점:
  - run_trade_cycle: 매 시간 9분(:09)에 호출. 매수/매도 모두 평가.
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
    settings = budget.settings
    ticker = settings.TICKER
    log.info(f"━━━ 매매 사이클 시작: {ticker} (mode={settings.EXIT_STRATEGY}) ━━━")

    # ── 1) 시세 / 지표 ─────────────────────────────
    df = api.get_ohlcv(ticker, interval="minute60", count=settings.CANDLE_COUNT)
    if df.empty and settings.EXIT_STRATEGY != "fixed":
        log.error("캔들 데이터 없음 — 사이클 스킵")
        return

    current_price = api.get_current_price(ticker)
    if current_price <= 0:
        log.error("현재가 조회 실패 — 사이클 스킵")
        return

    if df.empty:
        halt_vol = None
        log.warning("⚠ 캔들 데이터 없음 — fixed DCA는 변동성 차단 체크 없이 계속 진행")
    else:
        halt_vol = strategy.is_volatility_halt(df, settings)

    # ── 2) 잔고 / baseline ─────────────────────────
    coin_info = api.get_coin_balance(upbit, ticker)
    if coin_info is None:
        log.error("코인 잔고 확인 불가 — 포지션 상태를 보존하고 사이클 스킵")
        return
    exchange_vol  = coin_info["balance"]

    # 최초 1회: baseline 기록 (봇이 시작될 때의 사용자 기존 보유분)
    budget.ensure_baseline(exchange_vol)
    baseline_vol = budget.baseline_volume()
    bot_vol      = budget.bot_owned_volume(exchange_vol)

    log.info(f"잔고: 거래소={exchange_vol:.8f} | baseline(보호)={baseline_vol:.8f} | 봇운용={bot_vol:.8f}")

    # ── fixed 모드: 다중 포지션 분기 ────────────────
    if settings.EXIT_STRATEGY == "fixed":
        _run_fixed_cycle(upbit, ticker, current_price, exchange_vol, bot_vol, halt_vol, budget)
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    # ── trailing 모드 (기존 동작) ──────────────────
    if halt_vol:
        log.warning(f"⚠ 변동성 차단: {halt_vol} — 사이클 스킵")
        budget.print_status()
        return

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

        decision = strategy.evaluate_exit(position, current_price, df, settings)
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

    sig = strategy.get_buy_signal(df, current_price, settings)
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
    if slip is not None and slip > settings.SLIPPAGE_LIMIT_PCT:
        log.warning(f"⛔ 슬리피지 초과: {slip*100:+.2f}% > {settings.SLIPPAGE_LIMIT_PCT*100:.2f}% — 매수 취소")
        budget.print_status()
        log.info("━━━ 매매 사이클 종료 ━━━\n")
        return

    _execute_buy(upbit, ticker, current_price, sig, budget, exchange_vol)
    budget.print_status()
    log.info("━━━ 매매 사이클 종료 ━━━\n")


# ── 분 단위 exit 체크 ───────────────────────────────
def run_exit_check(budget: BudgetManager):
    """
    포지션 보유 중일 때만 매도 조건을 분 단위로 평가.
    무포지션이면 즉시 리턴 (저렴 — 파일 한 번 읽고 끝).
    매수 평가는 절대 하지 않음 (매수는 정시 run_trade_cycle 전용).
    """
    settings = budget.settings

    # fixed 모드: 다중 포지션 체크
    if settings.EXIT_STRATEGY == "fixed":
        positions = budget.load_positions()
        if not positions:
            return
        upbit = api.get_upbit_client()
        ticker = settings.TICKER
        current_price = api.get_current_price(ticker)
        if current_price <= 0:
            log.warning("[exit-check/fixed] 현재가 조회 실패 — 스킵")
            return
        coin_info = api.get_coin_balance(upbit, ticker)
        if coin_info is None:
            log.error("[exit-check/fixed] 코인 잔고 확인 불가 — 포지션 상태를 보존하고 스킵")
            return
        exchange_vol = coin_info["balance"]
        bot_vol = budget.bot_owned_volume(exchange_vol)
        positions = _reconcile_positions(positions, bot_vol, budget)
        if not positions:
            return
        _check_fixed_exits(upbit, ticker, positions, current_price, bot_vol, budget,
                           context="exit-check")
        return

    # trailing 모드 (기존 동작)
    position = budget.load_position()
    if position is None:
        return

    upbit  = api.get_upbit_client()
    ticker = settings.TICKER

    current_price = api.get_current_price(ticker)
    if current_price <= 0:
        log.warning("[exit-check] 현재가 조회 실패 — 스킵")
        return

    coin_info    = api.get_coin_balance(upbit, ticker)
    if coin_info is None:
        log.error("[exit-check] 코인 잔고 확인 불가 — 포지션 상태를 보존하고 스킵")
        return
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

    df = api.get_ohlcv(ticker, interval="minute60", count=settings.CANDLE_COUNT)
    decision = strategy.evaluate_exit(position, current_price, df, settings)

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
    if coin_info_after is None:
        log.error("⚠ 매수 후 잔고 확인 실패 — 잘못된 수량 기록을 막기 위해 포지션 생성 보류")
        return
    exchange_vol_after = coin_info_after["balance"]
    volume_purchased = exchange_vol_after - exchange_vol_before

    if volume_purchased <= 0:
        log.error(f"⚠ 매수 후 잔고 변화 없음 (before={exchange_vol_before}, after={exchange_vol_after}) — 포지션 미생성")
        return

    # 봇이 산 평균 매수가 (수수료 무시 근사)
    exec_price = amount / volume_purchased

    ind = sig["indicators"]
    entry_atr = float(ind.get("atr", 0))
    strategy_type = sig.get("strategy_type", "TREND")
    if strategy_type == "BB":
        from mean_revert import compute_stop_loss_bb
        stop_loss_price = compute_stop_loss_bb(exec_price, entry_atr, budget.settings)
    else:
        stop_loss_price = strategy.compute_stop_loss(exec_price, entry_atr, budget.settings)

    position = {
        "ticker":            ticker,
        "strategy_type":     strategy_type,
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
    if slip is not None and slip > budget.settings.SLIPPAGE_LIMIT_PCT:
        if action in ("STOP_LOSS", "TRAILING_STOP", "TREND_BREAK"):
            log.warning(f"⚠ 슬리피지 {slip*100:+.2f}% 이지만 {action} → 강제 매도")
        else:
            log.warning(f"⛔ 슬리피지 초과: {slip*100:+.2f}% > {budget.settings.SLIPPAGE_LIMIT_PCT*100:.2f}% — {action} 매도 취소")
            return

    log.info(f"💸 매도 시도: {safe_volume:.8f} ({action})")
    result = api.sell_market_order(upbit, ticker, safe_volume)
    if not result:
        log.error(f"매도 주문 실패 ({action})")
        return

    uuid = result.get("uuid") if isinstance(result, dict) else None
    order_info = None
    if uuid:
        order_info = api.wait_for_fill(upbit, uuid, timeout_sec=5.0)
    else:
        time.sleep(0.8)

    fill = api.summarize_order_fill(order_info or result)
    filled_volume = fill["executed_volume"]
    filled_funds = fill["executed_funds"]

    if fill["state"] and fill["state"] not in ("done", "cancel"):
        log.warning(f"⚠ 주문이 아직 종료 상태가 아님: state={fill['state']} uuid={uuid}")

    if filled_volume <= 0:
        log.warning(f"⚠ 체결 수량 확인 실패/미체결 — 상태 기록 스킵 ({action}, uuid={uuid}, order={order_info or result})")
        return

    if filled_volume > safe_volume:
        log.warning(f"⚠ 체결 수량이 요청 수량보다 큼: 체결={filled_volume:.8f}, 요청={safe_volume:.8f} → 요청 수량 기준으로 제한")
        filled_funds *= safe_volume / filled_volume if filled_funds > 0 else 0
        filled_volume = safe_volume

    # 손익 계산은 실제 체결 수량/금액 기준. 금액이 없으면 현재가 근사로만 fallback.
    entry_price = position["entry_price"]
    sold_volume = filled_volume
    buy_amount  = entry_price * sold_volume
    sell_amount = filled_funds if filled_funds > 0 else current_price * sold_volume
    sell_price  = sell_amount / sold_volume if sold_volume > 0 else current_price
    pnl         = sell_amount - buy_amount
    pnl_pct     = (sell_price - entry_price) / entry_price if entry_price > 0 else 0.0

    budget.record_sell(buy_amount, sell_amount, action)
    rec.record_sell(
        ticker=ticker, buy_price=entry_price, sell_price=sell_price,
        volume=sold_volume, buy_amount=buy_amount, sell_amount=sell_amount,
        pnl=pnl, pnl_pct=pnl_pct, reason=action,
    )
    sign = "+" if pnl >= 0 else ""
    log.info(f"✅ {action} 완료: {sell_price:,.0f}원 × {sold_volume:.8f} | 손익 {sign}{pnl:,.0f}원 ({sign}{pnl_pct*100:.2f}%)")

    # 포지션 갱신
    position["remaining_volume"] = max(0.0, position["remaining_volume"] - sold_volume)
    position_closed = position["remaining_volume"] <= 1e-12

    if action == "TP1":
        if position_closed:
            budget.clear_position()
            log.info("  → TP1 체결 후 잔량 없음: 포지션 종료")
        elif sold_volume + 1e-12 >= target_volume:
            position["tp1_done"] = True
            # 잔여물량 보호: 손절가를 본전(매수가)으로 상향
            position["stop_loss_price"] = max(position["stop_loss_price"], entry_price)
            budget.save_position(position)
            log.info(f"  → TP1 후: 잔량 {position['remaining_volume']:.8f}, 손절가 본전 {entry_price:,.0f}으로 상향")
        else:
            budget.save_position(position)
            log.warning(f"  → TP1 부분 체결: 목표={target_volume:.8f}, 체결={sold_volume:.8f}, 잔량={position['remaining_volume']:.8f}")
    elif action == "TP2":
        if position_closed:
            budget.clear_position()
            log.info("  → TP2 체결 후 잔량 없음: 포지션 종료")
        elif sold_volume + 1e-12 >= target_volume:
            position["tp2_done"] = True
            budget.save_position(position)
            log.info(f"  → TP2 후: 잔량 {position['remaining_volume']:.8f} (트레일링 -{budget.settings.TRAILING_STOP_PCT*100:.1f}% 적용 중)")
        else:
            budget.save_position(position)
            log.warning(f"  → TP2 부분 체결: 목표={target_volume:.8f}, 체결={sold_volume:.8f}, 잔량={position['remaining_volume']:.8f}")
    else:
        if position_closed:
            # 전량 매도 → 포지션 종료
            budget.clear_position()
            log.info("  → 포지션 종료")
        else:
            budget.save_position(position)
            log.warning(f"  → {action} 부분 체결: 잔량 {position['remaining_volume']:.8f} 유지")


# ── Fixed 모드 (다중 포지션 / +FIXED_TP_PCT 정액익절) ───────────
def _run_fixed_cycle(upbit, ticker: str, current_price: float,
                     exchange_vol: float, bot_vol: float, halt_vol,
                     budget: BudgetManager):
    """
    Fixed 모드 사이클:
      1) 보유 포지션 전체에 대해 +FIXED_TP_PCT 도달 체크 → 도달분 매도
      2) 변동성 차단 아니고, 일일 한도 안 걸렸으면, 매수 신호 평가
      3) 매수 가능(잔고 충분 + POSITION_PCT 한도)하면 신규 포지션 추가
    """
    positions = budget.load_positions()

    # 1) 매도 평가 (변동성 차단과 무관 — 익절은 항상 처리)
    positions = _reconcile_positions(positions, bot_vol, budget)
    positions = _check_fixed_exits(upbit, ticker, positions, current_price, bot_vol,
                                   budget, context="cycle")

    # 매도 후 거래소 잔고 재조회: _execute_buy_fixed의 volume_purchased 계산에 사용
    # (매도 전 exchange_vol을 그대로 쓰면 "bought - sold ≈ 0" 으로 포지션 누락됨)
    coin_info_post = api.get_coin_balance(upbit, ticker)
    if coin_info_post is None:
        log.error("[fixed] 매도 후 잔고 확인 불가 — 포지션 상태를 보존하고 신규 매수 스킵")
        budget.print_status()
        return
    exchange_vol = coin_info_post["balance"]

    # 2) 매수 평가
    if halt_vol:
        log.warning(f"⚠ 변동성 차단: {halt_vol} — 신규 매수만 스킵 (보유 매도는 처리됨)")
        budget.print_status()
        return

    halt = budget.is_trading_halted()
    if halt:
        log.info(f"⛔ 신규 매수 차단: {halt}")
        budget.print_status()
        return

    krw = api.get_krw_balance(upbit)
    if not budget.can_buy(krw):
        budget.print_status()
        return

    log.info(f"현재가={current_price:,.0f} | DCA 정시 매수")
    _execute_buy_fixed(upbit, ticker, current_price,
                       {"indicators": {}, "reason": "DCA 정시 매수"}, budget, exchange_vol)
    budget.print_status()


_MIN_MEANINGFUL_VOL = 1e-6   # 이보다 작은 잔량은 epsilon 오차 잔재 → phantom


def _reconcile_positions(positions: list, bot_vol: float, budget: BudgetManager) -> list:
    """
    포지션 파일의 극소 잔량만 정리하고 실제 잔고와의 불일치는 경고만 남긴다.

    API 오류·외부 이체·일시적 응답 이상을 phantom 포지션으로 오판할 수 있으므로,
    실제 잔고가 적다는 이유로 정상 포지션 기록을 자동 삭제하지 않는다.
    매도 수량은 _check_fixed_exits의 bot_vol 안전 캡에서 별도로 제한한다.
    """
    if not positions:
        return positions

    # ── 1단계: 극소 잔량 제거 ─────────────────────────────
    tiny = [p for p in positions if float(p.get("remaining_volume", 0)) < _MIN_MEANINGFUL_VOL]
    if tiny:
        positions = [p for p in positions if float(p.get("remaining_volume", 0)) >= _MIN_MEANINGFUL_VOL]
        for p in tiny:
            log.warning(
                f"⚠ [reconcile] 극소 잔량 phantom 제거: "
                f"entry={p.get('entry_price', 0):.0f}원 vol={p.get('remaining_volume')} "
                f"time={p.get('entry_time', '?')}"
            )
        budget.save_positions(positions)

    # 총량과 실제 잔고가 다르더라도 포지션 원장 자체는 보존한다.
    total = sum(float(p.get("remaining_volume", 0)) for p in positions)
    if total > bot_vol + 1e-6:
        log.error(
            f"⚠ [reconcile] 포지션 파일 총량({total:.8f}) > 봇 보유({bot_vol:.8f}) "
            f"— 자동 삭제하지 않고 {len(positions)}개 상태를 모두 보존"
        )
    return positions


def _check_fixed_exits(upbit, ticker: str, positions: list, current_price: float,
                       bot_vol: float, budget: BudgetManager, context: str) -> list:
    """
    각 포지션을 evaluate_exit으로 검사해서 FIXED_TP면 매도 실행.
    매도 후 남은 포지션 리스트를 반환 (호출측 처리 + 디스크 저장).
    bot_vol(거래소 잔고 - baseline)을 초과해서 매도하지 않도록 누적 캡 적용.
    """
    if not positions:
        return positions

    settings = budget.settings
    remaining_bot_vol = float(bot_vol)
    surviving = []

    for pos in positions:
        decision = strategy.evaluate_exit(pos, current_price, None, settings)
        action = decision["action"]
        if action != "FIXED_TP":
            surviving.append(pos)
            continue

        log.info(f"[{context}/fixed] {action} | {decision['reason']}")
        target_volume = pos.get("remaining_volume", 0)
        safe_volume = min(target_volume, remaining_bot_vol)
        if safe_volume <= 0:
            log.warning(f"⚠ baseline 보호 한도 → 이 포지션 매도 보류 (남은 매도 가능 {remaining_bot_vol:.8f})")
            surviving.append(pos)
            continue
        if safe_volume < target_volume:
            log.warning(f"⚠ 안전 캡 적용: 목표={target_volume:.8f} → 실제={safe_volume:.8f}")

        sold = _execute_sell_fixed(upbit, ticker, pos, safe_volume, current_price, budget, action=action)
        remaining_bot_vol = max(0.0, remaining_bot_vol - sold)
        # 전량 체결 여부: safe_volume 기준으로 판단 (1e-6 이내 오차는 완료로 처리)
        # target_volume 기준 비교 시 float 정밀도 차이로 잔량 1e-11 DOGE가 남아 무한 재매도됨
        fully_sold = (sold >= safe_volume - 1e-6) and (safe_volume >= target_volume - 1e-8)
        if not fully_sold:
            pos["remaining_volume"] = max(0.0, target_volume - sold)
            log.warning(f"  → {action} 부분 체결, 잔량 유지: {pos['remaining_volume']:.8f}")
            surviving.append(pos)

    if len(surviving) != len(positions):
        budget.save_positions(surviving)
    return surviving


def _execute_buy_fixed(upbit, ticker: str, current_price: float,
                       sig: dict, budget: BudgetManager, exchange_vol_before: float):
    """매수 실행 후 신규 포지션을 positions 리스트에 append."""
    settings = budget.settings
    amount = budget.order_amount()
    log.info(f"💰 [fixed] 매수 시도: {amount:,.0f}원 (현재가 {current_price:,.0f})")

    result = api.buy_market_order(upbit, ticker, amount)
    if not result:
        log.error("매수 주문 실패 — 포지션 미생성")
        return

    uuid = result.get("uuid") if isinstance(result, dict) else None
    if uuid:
        api.wait_for_fill(upbit, uuid, timeout_sec=5.0)
    else:
        time.sleep(0.8)

    coin_info_after = api.get_coin_balance(upbit, ticker)
    if coin_info_after is None:
        log.error("⚠ [fixed] 매수 후 잔고 확인 실패 — 잘못된 수량 기록을 막기 위해 포지션 생성 보류")
        return
    exchange_vol_after = coin_info_after["balance"]
    volume_purchased = exchange_vol_after - exchange_vol_before
    if volume_purchased <= 0:
        log.error(f"⚠ 매수 후 잔고 변화 없음 (before={exchange_vol_before}, after={exchange_vol_after}) — 포지션 미생성")
        return

    exec_price = amount / volume_purchased
    target_price = exec_price * (1 + settings.FIXED_TP_PCT)
    ind = sig.get("indicators", {})

    position = {
        "ticker":           ticker,
        "strategy_type":    "FIXED",
        "entry_price":      exec_price,
        "entry_time":       datetime.now(config.KST).strftime("%Y-%m-%d %H:%M:%S"),
        "initial_volume":   volume_purchased,
        "remaining_volume": volume_purchased,
        "krw_invested":     amount,
        "target_price":     target_price,
        "entry_atr":        float(ind.get("atr", 0)),
    }
    budget.add_position(position)
    budget.record_buy(amount)

    rec.record_buy(
        ticker=ticker, price=exec_price, volume=volume_purchased, amount_krw=amount,
        reason=sig.get("reason", ""),
        ma20=ind.get("ma20", 0), ma50=ind.get("ma50", 0), ma200=ind.get("ma200", 0),
        rsi=ind.get("rsi", 0), atr=ind.get("atr", 0),
        stop_loss=0,  # fixed 모드는 손절 없음
    )
    log.info(f"✅ [fixed] 매수 완료: {exec_price:,.0f}원 × {volume_purchased:.8f} = {amount:,.0f}원 | 목표 +{settings.FIXED_TP_PCT*100:.1f}% = {target_price:,.0f}")


def _execute_sell_fixed(upbit, ticker: str, position: dict, safe_volume: float,
                        current_price: float, budget: BudgetManager, action: str = "FIXED_TP") -> float:
    """단일 fixed 포지션 매도 실행. 실제 체결된 수량을 반환 (정상 매도 후 0이면 실패)."""
    slip = api.estimate_slippage(ticker, "SELL", current_price)
    if slip is not None and slip > budget.settings.SLIPPAGE_LIMIT_PCT:
        log.warning(f"⛔ 슬리피지 초과: {slip*100:+.2f}% > {budget.settings.SLIPPAGE_LIMIT_PCT*100:.2f}% — {action} 매도 취소")
        return 0.0

    log.info(f"💸 [fixed] 매도 시도: {safe_volume:.8f} ({action})")
    result = api.sell_market_order(upbit, ticker, safe_volume)
    if not result:
        log.error(f"매도 주문 실패 ({action})")
        return 0.0

    uuid = result.get("uuid") if isinstance(result, dict) else None
    order_info = api.wait_for_fill(upbit, uuid, timeout_sec=5.0) if uuid else None
    fill = api.summarize_order_fill(order_info or result)
    filled_volume = fill["executed_volume"]
    filled_funds = fill["executed_funds"]

    if filled_volume <= 0:
        log.warning(f"⚠ 체결 수량 확인 실패/미체결 — 상태 기록 스킵 (uuid={uuid})")
        return 0.0

    if filled_volume > safe_volume:
        filled_funds *= safe_volume / filled_volume if filled_funds > 0 else 0
        filled_volume = safe_volume

    entry_price = position["entry_price"]
    sold_volume = filled_volume
    buy_amount  = entry_price * sold_volume
    sell_amount = filled_funds if filled_funds > 0 else current_price * sold_volume
    sell_price  = sell_amount / sold_volume if sold_volume > 0 else current_price
    pnl         = sell_amount - buy_amount
    pnl_pct     = (sell_price - entry_price) / entry_price if entry_price > 0 else 0.0

    budget.record_sell(buy_amount, sell_amount, action)
    rec.record_sell(
        ticker=ticker, buy_price=entry_price, sell_price=sell_price,
        volume=sold_volume, buy_amount=buy_amount, sell_amount=sell_amount,
        pnl=pnl, pnl_pct=pnl_pct, reason=action,
    )
    sign = "+" if pnl >= 0 else ""
    log.info(f"✅ [fixed] {action} 완료: {sell_price:,.0f}원 × {sold_volume:.8f} | 손익 {sign}{pnl:,.0f}원 ({sign}{pnl_pct*100:.2f}%)")
    return sold_volume

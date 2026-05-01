"""
main.py — 자동매매 진입점
- 매수/매도 풀 사이클: 매 시간 9분(:09)에 실행
- 손절/TP/트레일링 체크: 분 단위 (포지션 보유 중일 때만 실제 동작)
"""
from __future__ import annotations
import schedule
import time

import config
from budget_manager import BudgetManager
from trader import run_trade_cycle, run_exit_check
from logger import get_logger

log = get_logger("main")


def job(budgets: list[BudgetManager]):
    for budget in budgets:
        try:
            run_trade_cycle(budget)
        except Exception as e:
            log.error(f"❌ 매매 사이클 예외 ({budget.settings.TICKER}): {e}", exc_info=True)


def exit_job(budgets: list[BudgetManager]):
    for budget in budgets:
        try:
            run_exit_check(budget)
        except Exception as e:
            log.error(f"❌ exit 체크 예외 ({budget.settings.TICKER}): {e}", exc_info=True)


def _log_market_settings(market):
    log.info(f"  [{market.name}] 티커:        {market.TICKER}")
    log.info(f"  [{market.name}] 배정예산:    {market.BUDGET:,.0f}원")
    log.info(f"  [{market.name}] 1회 진입:    {market.POSITION_PCT*100:.1f}% (유효예산 기준)")
    log.info(f"  [{market.name}] 손절:        {market.MAX_STOP_LOSS*100:.1f}% / ATR×{market.ATR_STOP_MULT}")
    log.info(f"  [{market.name}] 분할익절:    +{market.TP1_PCT*100:.1f}%×{market.TP1_RATIO*100:.0f}% / "
             f"+{market.TP2_PCT*100:.1f}%×{market.TP2_RATIO*100:.0f}%")
    log.info(f"  [{market.name}] 트레일링:    고점 대비 -{market.TRAILING_STOP_PCT*100:.1f}%")
    log.info(f"  [{market.name}] 추세 필터:   MA{market.MA_PULLBACK}/{market.MA_TREND_MID}/{market.MA_TREND_LONG}, "
             f"RSI({market.RSI_PERIOD})∈[{market.RSI_BUY_MIN},{market.ENTRY_RSI_MAX}], "
             f"P≤MA{market.MA_PULLBACK}×{1+market.ENTRY_PULLBACK_TOLERANCE:.3f}, "
             f"P≥MA{market.MA_TREND_MID}×{1-market.ENTRY_MID_MA_BUFFER_PCT:.3f}")
    if market.ENTRY_RANGE_LOOKBACK_BARS > 0:
        log.info(f"  [{market.name}] 고점추격방지: 최근 {market.ENTRY_RANGE_LOOKBACK_BARS}봉 범위 "
                 f"{market.ENTRY_RANGE_MAX_POSITION*100:.0f}% 이하에서만 진입")
    log.info(f"  [{market.name}] 추세이탈:   완성봉 MA{market.MA_TREND_MID}×"
             f"{1-market.TREND_BREAK_BUFFER_PCT:.3f} 하향 마감 "
             f"{market.TREND_BREAK_CONFIRM_BARS}회")
    log.info(f"  [{market.name}] BB 평균회귀: BB({market.BB_PERIOD},{market.BB_STD}σ), RSI<{market.BB_RSI_MAX:.0f}, "
             f"ATR스탑×{market.BB_ATR_STOP_MULT}, TIMEOUT {market.BB_MAX_HOLD_BARS}h")
    log.info(f"  [{market.name}] 상태파일:    {market.STATUS_FILE} / {market.POSITION_FILE} / {market.BASELINE_FILE}")


def main():
    config.validate()
    markets = config.active_markets()
    budgets = [BudgetManager(market) for market in markets]

    log.info("=" * 60)
    log.info("🤖 업비트 자동매매 (regime-aware: TREND 눌림목 + BB 평균회귀) 시작")
    log.info(f"  활성 종목:       {', '.join(m.TICKER for m in markets)}")
    for market in markets:
        _log_market_settings(market)
    log.info("=" * 60)

    log.info("▶ 시작 즉시 1회 실행")
    job(budgets)

    schedule.every().hour.at(":09").do(job, budgets=budgets)
    schedule.every(config.EXIT_CHECK_INTERVAL_MIN).minutes.do(exit_job, budgets=budgets)
    log.info(f"⏰ 스케줄 등록 — 매 정시 풀 사이클 + {config.EXIT_CHECK_INTERVAL_MIN}분마다 exit 체크")

    while True:
        schedule.run_pending()
        time.sleep(5)


if __name__ == "__main__":
    main()

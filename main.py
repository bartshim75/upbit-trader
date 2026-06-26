"""
main.py — 자동매매 진입점
- 매수: 매일 KST 03:08 (UTC 18:08) 1회 무조건 매수 (DCA)
- 익절 체크: 분 단위 (포지션 보유 중일 때만 실제 동작)
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
    log.info(f"  [{market.name}] 티커:     {market.TICKER}")
    log.info(f"  [{market.name}] 배정예산: {market.BUDGET:,.0f}원  |  1회 진입: {market.POSITION_PCT*100:.1f}%")
    log.info(f"  [{market.name}] 익절 목표: +{market.FIXED_TP_PCT*100:.1f}%  |  손절: 없음 (무제한 보유)")
    log.info(f"  [{market.name}] 상태파일: {market.STATUS_FILE} / {market.POSITIONS_FILE}")


def main():
    config.validate()
    markets = config.active_markets()
    budgets = [BudgetManager(market) for market in markets]

    log.info("=" * 60)
    log.info("🤖 업비트 자동매매 (DCA: 매일 03:08 KST 매수, 목표가 도달 시 익절) 시작")
    log.info(f"  활성 종목:       {', '.join(m.TICKER for m in markets)}")
    for market in markets:
        _log_market_settings(market)
    log.info("=" * 60)

    schedule.every().day.at("18:08").do(job, budgets=budgets)   # KST 03:08
    schedule.every(config.EXIT_CHECK_INTERVAL_MIN).minutes.do(exit_job, budgets=budgets)
    log.info(f"⏰ 스케줄 등록 — 매일 18:08 UTC(=KST 03:08) 매수 + {config.EXIT_CHECK_INTERVAL_MIN}분마다 익절 체크")

    while True:
        schedule.run_pending()
        time.sleep(5)


if __name__ == "__main__":
    main()

"""
main.py — 자동매매 진입점
- 매수: 매일 KST 03:08 (UTC 18:08) 1회 무조건 매수 (DCA)
- 익절 체크: 분 단위 (포지션 보유 중일 때만 실제 동작)
"""
from __future__ import annotations
from contextlib import contextmanager
import signal
import schedule
import time
from datetime import datetime, timedelta

import config
from budget_manager import BudgetManager
from trader import run_trade_cycle, run_exit_check
from log_rotator import rotate_logs
from logger import get_logger

log = get_logger("main")


class JobTimeoutError(TimeoutError):
    pass


@contextmanager
def _time_limit(seconds: int, label: str):
    """단일 schedule job이 API 호출에서 hang되어 전체 루프를 막지 않도록 제한."""
    if seconds <= 0:
        yield
        return

    def _raise_timeout(_signum, _frame):
        raise JobTimeoutError(f"{label} timeout ({seconds}s)")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def job(budgets: list[BudgetManager]):
    for budget in budgets:
        ticker = budget.settings.TICKER
        try:
            with _time_limit(config.TRADE_CYCLE_TIMEOUT_SEC, f"trade_cycle {ticker}"):
                run_trade_cycle(budget)
        except JobTimeoutError as e:
            log.error(f"⏱️ 매매 사이클 타임아웃 ({ticker}): {e}", exc_info=True)
        except Exception as e:
            log.error(f"❌ 매매 사이클 예외 ({ticker}): {e}", exc_info=True)


def exit_job(budgets: list[BudgetManager]):
    for budget in budgets:
        ticker = budget.settings.TICKER
        try:
            with _time_limit(config.EXIT_CHECK_TIMEOUT_SEC, f"exit_check {ticker}"):
                run_exit_check(budget)
        except JobTimeoutError as e:
            log.error(f"⏱️ exit 체크 타임아웃 ({ticker}): {e}", exc_info=True)
        except Exception as e:
            log.error(f"❌ exit 체크 예외 ({ticker}): {e}", exc_info=True)


def _log_market_settings(market):
    log.info(f"  [{market.name}] 티커:     {market.TICKER}")
    log.info(f"  [{market.name}] 배정예산: {market.BUDGET:,.0f}원  |  1회 진입: {market.POSITION_PCT*100:.1f}%")
    if market.EXIT_STRATEGY == "fixed":
        log.info(f"  [{market.name}] 매도: 평단 +3% 30% / +6% 60% / +9% 전량 | 체결 후 24시간 쿨다운 | 손절 없음")
    else:
        log.info(f"  [{market.name}] 매도: TP1/TP2/트레일링/손절/추세이탈")
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

    schedule.every().day.at("18:08").do(job, budgets=budgets)              # KST 03:08 매수
    schedule.every(config.EXIT_CHECK_INTERVAL_MIN).minutes.do(exit_job, budgets=budgets)
    schedule.every().monday.at("00:00").do(rotate_logs)                    # KST 09:00 로그 로테이션 (짝수 주차)
    log.info(f"⏰ 스케줄 등록 — 매일 18:08 UTC(=KST 03:08) 매수 + {config.EXIT_CHECK_INTERVAL_MIN}분마다 익절 체크 + 짝수주 월요일 로그 로테이션")

    next_heartbeat = datetime.now(config.KST) + timedelta(minutes=10)
    while True:
        schedule.run_pending()
        now = datetime.now(config.KST)
        if now >= next_heartbeat:
            next_runs = sorted(
                job.next_run.strftime("%Y-%m-%d %H:%M:%S")
                for job in schedule.jobs
                if job.next_run is not None
            )
            log.info(f"💓 scheduler alive — next_run={', '.join(next_runs[:5])}")
            next_heartbeat = now + timedelta(minutes=10)
        time.sleep(5)


if __name__ == "__main__":
    main()

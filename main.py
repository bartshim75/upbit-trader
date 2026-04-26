"""
main.py — 자동매매 진입점
1시간마다 매매 사이클을 실행합니다.
"""
import schedule
import time
from datetime import datetime

import config
from budget_manager import BudgetManager
from trader import run_trade_cycle
from logger import get_logger

log = get_logger("main")


def job(budget: BudgetManager):
    """스케줄러가 매 정시에 호출하는 작업"""
    try:
        run_trade_cycle(budget)
    except Exception as e:
        log.error(f"❌ 매매 사이클 예외 발생: {e}", exc_info=True)


def main():
    log.info("=" * 60)
    log.info("🤖 업비트 자동매매 시작")
    log.info(f"   티커:      {config.TICKER}")
    log.info(f"   배정예산:  {config.BUDGET:,.0f}원")
    log.info(f"   1회매수:   {config.ORDER_AMOUNT:,.0f}원")
    log.info(f"   손절선:    {config.STOP_LOSS*100:.1f}%")
    log.info(f"   익절선:    {config.TAKE_PROFIT*100:.1f}%")
    log.info(f"   MA단기/장기: {config.MA_SHORT} / {config.MA_LONG}봉")
    log.info("=" * 60)

    # 설정 유효성 검사
    config.validate()

    budget = BudgetManager()

    # 시작하자마자 1회 즉시 실행
    log.info("▶ 시작 즉시 1회 실행")
    job(budget)

    # 이후 매 정시 실행 (예: 10:00, 11:00, 12:00 ...)
    schedule.every().hour.at(":00").do(job, budget=budget)
    log.info("⏰ 스케줄 등록 완료 — 매 정시에 실행됩니다")

    while True:
        schedule.run_pending()
        time.sleep(30)  # 30초마다 스케줄 체크


if __name__ == "__main__":
    main()

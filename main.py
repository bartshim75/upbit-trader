"""
main.py — 자동매매 진입점
1시간마다 매매 사이클을 실행합니다.
"""
import schedule
import time

import config
from budget_manager import BudgetManager
from trader import run_trade_cycle
from logger import get_logger

log = get_logger("main")


def job(budget: BudgetManager):
    try:
        run_trade_cycle(budget)
    except Exception as e:
        log.error(f"❌ 매매 사이클 예외: {e}", exc_info=True)


def main():
    log.info("=" * 60)
    log.info("🤖 업비트 자동매매 (1H 추세 눌림목 전략) 시작")
    log.info(f"  티커:           {config.TICKER}")
    log.info(f"  배정예산:       {config.BUDGET:,.0f}원")
    log.info(f"  1회 진입 비율:  {config.POSITION_PCT*100:.1f}% (유효예산 기준)")
    log.info(f"  손절 한도:      {config.MAX_STOP_LOSS*100:.1f}% / ATR×{config.ATR_STOP_MULT}")
    log.info(f"  분할 익절:      +{config.TP1_PCT*100:.1f}%×{config.TP1_RATIO*100:.0f}% / "
             f"+{config.TP2_PCT*100:.1f}%×{config.TP2_RATIO*100:.0f}%")
    log.info(f"  트레일링:       고점 대비 -{config.TRAILING_STOP_PCT*100:.1f}%")
    log.info(f"  추세 필터:      MA{config.MA_PULLBACK}/{config.MA_TREND_MID}/{config.MA_TREND_LONG}, "
             f"RSI({config.RSI_PERIOD})∈[{config.RSI_BUY_MIN},{config.RSI_BUY_MAX}]")
    log.info(f"  일일 손실 한도: -{config.DAILY_LOSS_LIMIT_PCT*100:.1f}% / 연속손절 {config.MAX_CONSECUTIVE_STOPS}회")
    log.info(f"  슬리피지 한도:  {config.SLIPPAGE_LIMIT_PCT*100:.2f}%")
    log.info("=" * 60)

    config.validate()
    budget = BudgetManager()

    log.info("▶ 시작 즉시 1회 실행")
    job(budget)

    schedule.every().hour.at(":00").do(job, budget=budget)
    log.info("⏰ 스케줄 등록 — 매 정시 실행")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

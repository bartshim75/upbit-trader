"""
budget_manager.py — 예산 관리 모듈
배정 예산 내에서만 매매하고, 잔여 예산을 추적합니다.
"""
import json
import os
from datetime import datetime
import config
from logger import get_logger

log = get_logger(__name__)


class BudgetManager:
    def __init__(self):
        self.status_file = config.STATUS_FILE
        self.status = self._load_status()

    def _load_status(self) -> dict:
        """저장된 상태 불러오기 (없으면 초기화)"""
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # 최초 초기화
        return {
            "배정예산":         config.BUDGET,
            "누적투자금":       0,
            "누적실현손익":     0,
            "총거래횟수":       0,
            "매수횟수":         0,
            "매도횟수":         0,
            "손절횟수":         0,
            "익절횟수":         0,
            "데드크로스매도횟수": 0,
            "승률":             0.0,
            "시작일":           datetime.now().strftime("%Y-%m-%d %H:%M"),
            "최종업데이트":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def save_status(self):
        """상태 저장"""
        self.status["최종업데이트"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(self.status, f, ensure_ascii=False, indent=2)

    def can_buy(self, krw_balance: float) -> bool:
        """
        매수 가능 여부 판단
        - 실제 KRW 잔고가 1회 매수금액 이상
        - 배정 예산 내에서 아직 투자 여력이 있음
        """
        # 배정예산 기준 잔여 투자 여력
        realized_pnl    = self.status["누적실현손익"]
        total_invested  = self.status["누적투자금"]

        # 현재 운용 자산 = 배정예산 + 실현손익 (손익이 반영된 실질 예산)
        effective_budget = config.BUDGET + realized_pnl

        # 이미 투자된 금액이 유효 예산을 초과하면 신규 매수 불가
        # (현재 보유 포지션이 있다면 해당 금액만큼 차감)
        if total_invested >= effective_budget:
            log.info(f"⛔ 예산 한도 도달: 유효예산={effective_budget:,.0f}원, 투자중={total_invested:,.0f}원")
            return False

        # 실제 잔고 확인
        if krw_balance < config.ORDER_AMOUNT:
            log.info(f"⛔ 잔고 부족: 잔고={krw_balance:,.0f}원, 필요={config.ORDER_AMOUNT:,.0f}원")
            return False

        log.info(f"✅ 매수 가능: 잔고={krw_balance:,.0f}원, 유효예산={effective_budget:,.0f}원")
        return True

    def record_buy(self, amount_krw: float):
        """매수 기록"""
        self.status["누적투자금"] += amount_krw
        self.status["매수횟수"]   += 1
        self.status["총거래횟수"] += 1
        self.save_status()

    def record_sell(self, buy_amount: float, sell_amount: float, reason: str):
        """
        매도 기록 및 손익 업데이트
        reason: "STOP_LOSS" / "TAKE_PROFIT" / "DEAD_CROSS"
        """
        pnl = sell_amount - buy_amount
        self.status["누적실현손익"] += pnl
        self.status["누적투자금"]   = max(0, self.status["누적투자금"] - buy_amount)
        self.status["매도횟수"]     += 1
        self.status["총거래횟수"]   += 1

        if reason == "STOP_LOSS":
            self.status["손절횟수"] += 1
        elif reason == "TAKE_PROFIT":
            self.status["익절횟수"] += 1
        elif reason == "DEAD_CROSS":
            self.status["데드크로스매도횟수"] += 1

        # 승률 계산 (익절 / 전체매도)
        total_sells = self.status["매도횟수"]
        if total_sells > 0:
            self.status["승률"] = round(self.status["익절횟수"] / total_sells * 100, 1)

        self.save_status()
        return pnl

    def print_status(self):
        """현재 상태 출력"""
        s = self.status
        pnl = s["누적실현손익"]
        pnl_str = f"+{pnl:,.0f}원" if pnl >= 0 else f"{pnl:,.0f}원"
        pnl_pct = pnl / config.BUDGET * 100

        log.info("=" * 50)
        log.info(f"📊 현황 요약")
        log.info(f"  배정예산:      {config.BUDGET:>12,.0f}원")
        log.info(f"  누적실현손익:  {pnl_str:>12}")
        log.info(f"  손익률:        {pnl_pct:>+11.2f}%")
        log.info(f"  총거래횟수:    {s['총거래횟수']:>12}회")
        log.info(f"  승률:          {s['승률']:>11.1f}%")
        log.info(f"  (익절:{s['익절횟수']} / 손절:{s['손절횟수']} / 데드크로스:{s['데드크로스매도횟수']})")
        log.info("=" * 50)

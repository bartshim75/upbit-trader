"""
budget_manager.py — 예산 / 일일 리스크 / 포지션 상태 관리
- 배정 예산 내에서만 매매
- 일일 누적 손실이 BUDGET * DAILY_LOSS_LIMIT_PCT 초과 시 당일 신규 매수 차단
- 연속 손절 MAX_CONSECUTIVE_STOPS 회 도달 시 당일 신규 매수 차단
- 보유 포지션 상태(고점, 부분매도 진행, ATR 기반 손절가) 영속화
"""
import json
import os
from datetime import datetime, date
from typing import Optional
import config
from logger import get_logger

log = get_logger(__name__)


def _today_str() -> str:
    return date.today().isoformat()


class BudgetManager:
    def __init__(self):
        self.status_file   = config.STATUS_FILE
        self.position_file = config.POSITION_FILE
        self.baseline_file = config.BASELINE_FILE
        self.status = self._load_status()
        self._reset_daily_if_new_day()

    # ── 상태 로드/저장 ──────────────────────────────
    def _load_status(self) -> dict:
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    s = json.load(f)
                # 누락 필드 보강
                s.setdefault("일일", self._empty_daily())
                return s
            except Exception:
                pass
        return {
            "배정예산":         config.BUDGET,
            "누적투자금":       0,
            "누적실현손익":     0,
            "총거래횟수":       0,
            "매수횟수":         0,
            "매도횟수":         0,
            "손절횟수":         0,
            "익절횟수":         0,
            "트레일링매도횟수": 0,
            "추세이탈매도횟수": 0,
            "승률":             0.0,
            "시작일":           datetime.now().strftime("%Y-%m-%d %H:%M"),
            "최종업데이트":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "일일":             self._empty_daily(),
        }

    def _empty_daily(self) -> dict:
        return {
            "날짜": _today_str(),
            "실현손익": 0,
            "연속손절": 0,
            "거래중단": False,
            "중단사유": "",
        }

    def _reset_daily_if_new_day(self):
        d = self.status.get("일일", self._empty_daily())
        if d.get("날짜") != _today_str():
            log.info(f"📅 새 거래일 시작: 일일 카운터 초기화 (이전 {d.get('날짜')})")
            self.status["일일"] = self._empty_daily()
            self.save_status()

    def save_status(self):
        self.status["최종업데이트"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(self.status, f, ensure_ascii=False, indent=2)

    # ── 일일 한도 / 차단 ───────────────────────────
    def daily_loss_limit(self) -> float:
        return -abs(config.BUDGET * config.DAILY_LOSS_LIMIT_PCT)

    def is_trading_halted(self) -> Optional[str]:
        """차단되어 있으면 사유 문자열, 아니면 None"""
        self._reset_daily_if_new_day()
        d = self.status["일일"]
        if d.get("거래중단"):
            return d.get("중단사유", "거래 중단 플래그")
        if d["실현손익"] <= self.daily_loss_limit():
            return f"일일 손실 한도 도달 ({d['실현손익']:+,.0f}원 ≤ {self.daily_loss_limit():,.0f}원)"
        if d["연속손절"] >= config.MAX_CONSECUTIVE_STOPS:
            return f"연속 손절 {d['연속손절']}회 도달 (한도 {config.MAX_CONSECUTIVE_STOPS})"
        return None

    def halt_trading(self, reason: str):
        self._reset_daily_if_new_day()
        self.status["일일"]["거래중단"] = True
        self.status["일일"]["중단사유"] = reason
        self.save_status()
        log.warning(f"🛑 당일 거래 중단: {reason}")

    # ── 매수 가능 여부 ──────────────────────────────
    def effective_budget(self) -> float:
        """현재 운용 자산 = 배정예산 + 누적실현손익"""
        return config.BUDGET + self.status["누적실현손익"]

    def order_amount(self) -> int:
        """1회 진입 금액 = 유효예산 * POSITION_PCT (최소 주문금액 보장)"""
        amt = int(self.effective_budget() * config.POSITION_PCT)
        return max(amt, config.MIN_ORDER_KRW)

    def can_buy(self, krw_balance: float) -> bool:
        halt = self.is_trading_halted()
        if halt:
            log.info(f"⛔ 매수 불가: {halt}")
            return False

        amt = self.order_amount()
        eff = self.effective_budget()
        if self.status["누적투자금"] + amt > eff:
            log.info(f"⛔ 예산 한도 도달: 유효예산={eff:,.0f}, 투자중={self.status['누적투자금']:,.0f}, 신규={amt:,.0f}")
            return False
        if krw_balance < amt:
            log.info(f"⛔ 잔고 부족: 잔고={krw_balance:,.0f}원, 필요={amt:,.0f}원")
            return False
        log.info(f"✅ 매수 가능: 잔고={krw_balance:,.0f}원, 1회진입={amt:,.0f}원, 유효예산={eff:,.0f}원")
        return True

    # ── 매수/매도 기록 ──────────────────────────────
    def record_buy(self, amount_krw: float):
        self.status["누적투자금"] += amount_krw
        self.status["매수횟수"]   += 1
        self.status["총거래횟수"] += 1
        self.save_status()

    def record_sell(self, buy_amount: float, sell_amount: float, reason: str):
        """
        reason: STOP_LOSS / TP1 / TP2 / TRAILING_STOP / TREND_BREAK
        """
        self._reset_daily_if_new_day()
        pnl = sell_amount - buy_amount
        self.status["누적실현손익"] += pnl
        self.status["누적투자금"]   = max(0, self.status["누적투자금"] - buy_amount)
        self.status["매도횟수"]     += 1
        self.status["총거래횟수"]   += 1

        if reason == "STOP_LOSS":
            self.status["손절횟수"] += 1
            self.status["일일"]["연속손절"] += 1
        elif reason in ("TP1", "TP2"):
            self.status["익절횟수"] += 1
            self.status["일일"]["연속손절"] = 0
        elif reason == "TRAILING_STOP":
            self.status["트레일링매도횟수"] += 1
            # 트레일링은 보통 익절 방향 → 손익 부호로 연속손절 카운터 갱신
            if pnl >= 0:
                self.status["일일"]["연속손절"] = 0
            else:
                self.status["일일"]["연속손절"] += 1
        elif reason == "TREND_BREAK":
            self.status["추세이탈매도횟수"] += 1
            if pnl < 0:
                self.status["일일"]["연속손절"] += 1
            else:
                self.status["일일"]["연속손절"] = 0

        self.status["일일"]["실현손익"] += pnl

        sells = self.status["매도횟수"]
        wins  = self.status["익절횟수"] + self.status["트레일링매도횟수"]
        if sells > 0:
            self.status["승률"] = round(wins / sells * 100, 1)

        self.save_status()

        # 한도 점검
        halt = self.is_trading_halted()
        if halt and not self.status["일일"]["거래중단"]:
            self.halt_trading(halt)
        return pnl

    # ── 사용자 기존 보유분 (baseline) 보호 ────────────
    def load_baseline(self) -> Optional[dict]:
        """
        baseline.json: {"volume": 0.001, "recorded_at": "...", "note": "..."}
        없으면 None.
        """
        if not os.path.exists(self.baseline_file):
            return None
        try:
            with open(self.baseline_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_baseline(self, volume: float, note: str = ""):
        data = {
            "volume": float(volume),
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": note,
        }
        with open(self.baseline_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"📌 baseline 기록: {volume:.8f} ({note})")

    def baseline_volume(self) -> float:
        b = self.load_baseline()
        return float(b["volume"]) if b else 0.0

    def ensure_baseline(self, current_exchange_volume: float):
        """
        최초 1회: baseline.json이 없으면 현재 거래소 잔고를 baseline으로 기록.
        이후 봇은 이 baseline 이상으로만 매도 가능 (기존 자산 보호).
        """
        if self.load_baseline() is not None:
            return
        self.save_baseline(
            current_exchange_volume,
            note="자동 기록: 봇 첫 실행 시점의 사용자 보유 수량 (이 수량은 절대 매도하지 않음)",
        )

    def bot_owned_volume(self, exchange_volume: float) -> float:
        """봇이 매도 가능한 수량 = 현재 거래소 잔고 - baseline (음수면 0)"""
        return max(0.0, exchange_volume - self.baseline_volume())

    # ── 포지션 상태 영속화 ──────────────────────────
    def load_position(self) -> Optional[dict]:
        if not os.path.exists(self.position_file):
            return None
        try:
            with open(self.position_file, "r", encoding="utf-8") as f:
                p = json.load(f)
            return p if p.get("entry_price", 0) > 0 else None
        except Exception:
            return None

    def save_position(self, position: dict):
        with open(self.position_file, "w", encoding="utf-8") as f:
            json.dump(position, f, ensure_ascii=False, indent=2)

    def clear_position(self):
        if os.path.exists(self.position_file):
            os.remove(self.position_file)

    # ── API 오류 카운터 (사이클 단위) ──────────────
    def reset_api_errors(self):
        self._api_errors = 0

    def bump_api_errors(self) -> int:
        self._api_errors = getattr(self, "_api_errors", 0) + 1
        return self._api_errors

    # ── 상태 출력 ──────────────────────────────────
    def print_status(self):
        s = self.status
        d = s["일일"]
        pnl = s["누적실현손익"]
        pnl_str = f"+{pnl:,.0f}원" if pnl >= 0 else f"{pnl:,.0f}원"
        pnl_pct = pnl / config.BUDGET * 100 if config.BUDGET else 0

        log.info("=" * 56)
        log.info("📊 현황 요약")
        log.info(f"  배정예산:      {config.BUDGET:>12,.0f}원")
        log.info(f"  유효예산:      {self.effective_budget():>12,.0f}원")
        log.info(f"  누적실현손익:  {pnl_str:>12}  ({pnl_pct:+.2f}%)")
        log.info(f"  1회 진입금액:  {self.order_amount():>12,.0f}원")
        log.info(f"  총거래/승률:   {s['총거래횟수']:>12}회 / {s['승률']:.1f}%")
        log.info(f"   (TP:{s['익절횟수']} TS:{s['트레일링매도횟수']} TB:{s['추세이탈매도횟수']} SL:{s['손절횟수']})")
        log.info(f"  오늘({d['날짜']}): {d['실현손익']:+,.0f}원, 연속손절 {d['연속손절']}회"
                 + (f"  ⚠ 차단: {d['중단사유']}" if d.get('거래중단') else ""))
        log.info("=" * 56)

"""
mean_revert.py — 횡보장용 BB 하단 평균회귀 전략

매수 조건 (모두 만족):
  1. 현재가 ≤ BB 하단 * (1 + BB_TOL)            (밴드 하단 또는 살짝 안)
  2. 양봉 반등 (현재 봉 close > open)
  3. RSI < BB_RSI_MAX                             (과매도)
  4. 현재가 > MA200 * BB_MA200_FLOOR              (대폭락/이탈 회피)

매도 조건 (단일 exit, 전량 매도):
  - STOP_LOSS: 현재가 ≤ 손절가 (= entry - BB_ATR_STOP_MULT × 진입ATR)
  - TARGET   : 현재가 ≥ SMA20(BB 중간선) → 평균회귀 도달
  - TIMEOUT  : 진입 후 BB_MAX_HOLD_BARS 시간 경과
"""
from datetime import datetime
import pandas as pd
import config
from logger import get_logger

log = get_logger(__name__)


def calc_bb(df: pd.DataFrame) -> pd.DataFrame:
    """BB 하단/중간/상단 컬럼 추가."""
    df = df.copy()
    sma = df["close"].rolling(window=config.BB_PERIOD).mean()
    sd  = df["close"].rolling(window=config.BB_PERIOD).std()
    df["bb_mid"]   = sma
    df["bb_lower"] = sma - config.BB_STD * sd
    df["bb_upper"] = sma + config.BB_STD * sd
    return df


def get_buy_signal_bb(df: pd.DataFrame, current_price: float) -> dict:
    """BB 하단 평균회귀 매수 신호. 반환 dict 형식은 strategy.get_buy_signal과 동일.
    추가로 'strategy_type': 'BB' 필드를 반환한다."""
    from strategy import calc_indicators  # MA200 / RSI / ATR
    base = {"signal": "HOLD", "reason": "", "indicators": {}, "strategy_type": "BB"}

    if df.empty or len(df) < max(config.MA_TREND_LONG, config.BB_PERIOD) + 5:
        base["reason"] = "데이터 부족"
        return base

    ind = calc_indicators(df)
    bb  = calc_bb(df)
    cur    = ind.iloc[-1]
    cur_bb = bb.iloc[-1]

    ma200    = cur["ma200"]
    rsi      = cur["rsi"]
    atr      = cur["atr"]
    bb_lower = cur_bb["bb_lower"]
    bb_mid   = cur_bb["bb_mid"]
    bb_upper = cur_bb["bb_upper"]

    if any(pd.isna([ma200, rsi, atr, bb_lower, bb_mid])):
        base["reason"] = "지표 계산 중"
        return base

    indicators = {
        "ma200": float(ma200), "rsi": float(rsi), "atr": float(atr),
        "bb_lower": float(bb_lower), "bb_mid": float(bb_mid), "bb_upper": float(bb_upper),
    }
    base["indicators"] = indicators

    cond_band    = current_price <= bb_lower * (1 + config.BB_TOL)
    cond_rebound = float(cur["close"]) > float(cur["open"])
    cond_rsi     = rsi < config.BB_RSI_MAX
    cond_floor   = current_price > ma200 * config.BB_MA200_FLOOR

    checks = {
        f"BB하단(P≤bb_low·{1+config.BB_TOL:.3f})": cond_band,
        "양봉반등(close>open)":                     cond_rebound,
        f"RSI<{config.BB_RSI_MAX:.0f}":              cond_rsi,
        f"P>MA200·{config.BB_MA200_FLOOR}":          cond_floor,
    }

    if all(checks.values()):
        reason = (
            f"BB-BUY ✓ 평균회귀 (P={current_price:,.0f}, BB하단={bb_lower:,.0f}, "
            f"BB중간={bb_mid:,.0f}, RSI={rsi:.1f}, ATR={atr:,.0f})"
        )
        return {"signal": "BUY", "reason": reason, "indicators": indicators, "strategy_type": "BB"}

    failed = [k for k, v in checks.items() if not v]
    base["reason"] = (
        f"BB-BUY 보류 — 미충족: {', '.join(failed)} "
        f"(P={current_price:,.0f}, BB하단={bb_lower:,.0f}, RSI={rsi:.1f})"
    )
    return base


def evaluate_exit_bb(position: dict, current_price: float, df: pd.DataFrame) -> dict:
    """BB 모드 매도 판정 — 단일 exit, 전량 매도."""
    out = {"action": "HOLD", "sell_ratio": 0.0, "reason": "", "indicators": {}}

    entry_price = position["entry_price"]
    pnl_pct     = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

    bb_mid = None
    if not df.empty and len(df) >= config.BB_PERIOD:
        sma_series = df["close"].rolling(window=config.BB_PERIOD).mean()
        if not pd.isna(sma_series.iloc[-1]):
            bb_mid = float(sma_series.iloc[-1])
    out["indicators"] = {"bb_mid": bb_mid, "pnl_pct": pnl_pct}

    # 1) STOP_LOSS (최우선)
    if current_price <= position["stop_loss_price"]:
        return {
            "action": "STOP_LOSS",
            "sell_ratio": 1.0,
            "reason": (f"STOP_LOSS 매수가={entry_price:,.0f} 손절가={position['stop_loss_price']:,.0f} "
                       f"현재가={current_price:,.0f} ({pnl_pct*100:+.2f}%)"),
            "indicators": out["indicators"],
        }

    # 2) TARGET (BB 중간선 도달)
    if bb_mid is not None and current_price >= bb_mid:
        return {
            "action": "TARGET",
            "sell_ratio": 1.0,
            "reason": f"TARGET BB중간선 도달 (P={current_price:,.0f} ≥ SMA20={bb_mid:,.0f}, {pnl_pct*100:+.2f}%)",
            "indicators": out["indicators"],
        }

    # 3) TIMEOUT
    entry_time_str = position.get("entry_time")
    if entry_time_str:
        try:
            entry_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.KST)
            now_dt   = datetime.now(config.KST)
            hours_held = (now_dt - entry_dt).total_seconds() / 3600
            if hours_held >= config.BB_MAX_HOLD_BARS:
                return {
                    "action": "TIMEOUT",
                    "sell_ratio": 1.0,
                    "reason": f"TIMEOUT 보유 {hours_held:.1f}h ≥ {config.BB_MAX_HOLD_BARS}h ({pnl_pct*100:+.2f}%)",
                    "indicators": out["indicators"],
                }
        except (ValueError, TypeError):
            pass

    out["reason"] = f"BB 보유중 ({pnl_pct*100:+.2f}%)"
    return out


def compute_stop_loss_bb(entry_price: float, entry_atr: float) -> float:
    """BB 모드 손절가 = entry - BB_ATR_STOP_MULT × ATR (와이드 스탑, 평균회귀 친화)."""
    return entry_price - config.BB_ATR_STOP_MULT * entry_atr

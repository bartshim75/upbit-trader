"""
strategy.py — 1시간봉 추세 눌림목 전략

매수 조건 (모두 만족):
  1. 현재가 > MA200                     (상승 추세)
  2. MA50 > MA200                       (중기 추세 정렬)
  3. 현재가 <= MA20 * (1 + tolerance)   (눌림목)
  4. RSI(14) ∈ [30, 55]                 (과매도 반등 / 과열 회피)
  5. 반등 캔들 (현재 종가 > 직전 고가  또는  현재 종가 > 현재 시가)

매도 조건:
  - 손절: max(매수가 * (1 + MAX_STOP_LOSS), 매수가 - ATR_STOP_MULT * ATR_at_entry)
  - 1차 익절: +TP1_PCT 도달 → 보유의 TP1_RATIO 매도
  - 2차 익절: +TP2_PCT 도달 → 보유의 TP2_RATIO 매도
  - 잔여 물량: 진입 후 고점 대비 -TRAILING_STOP_PCT 하락 시 전량 매도
  - 추세 이탈: 현재가 < MA50 → 잔여 전량 매도

거래 차단:
  - 직전 1시간봉 변동폭(고가-저가)이 ATR * VOLATILITY_HALT_MULT 이상
"""
from typing import Optional
import pandas as pd
import numpy as np
import config
from logger import get_logger

log = get_logger(__name__)


# ── 지표 계산 ────────────────────────────────────────

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """MA20/50/200, RSI, ATR을 계산해 컬럼으로 추가"""
    df = df.copy()
    df["ma20"]  = df["close"].rolling(window=config.MA_PULLBACK).mean()
    df["ma50"]  = df["close"].rolling(window=config.MA_TREND_MID).mean()
    df["ma200"] = df["close"].rolling(window=config.MA_TREND_LONG).mean()
    df["rsi"]   = _rsi(df["close"], config.RSI_PERIOD)
    df["atr"]   = _atr(df, config.ATR_PERIOD)
    return df


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ── 매수 신호 ────────────────────────────────────────

def get_buy_signal(df: pd.DataFrame, current_price: float) -> dict:
    """
    매수 신호 평가. 결과 dict:
      signal: "BUY" / "HOLD"
      reason: 사유 문자열
      indicators: ma20, ma50, ma200, rsi, atr
    """
    base = {"signal": "HOLD", "reason": "", "indicators": {}}

    if df.empty or len(df) < config.MA_TREND_LONG + 5:
        base["reason"] = "데이터 부족"
        return base

    ind = calc_indicators(df)
    cur, prev = ind.iloc[-1], ind.iloc[-2]

    ma20, ma50, ma200 = cur["ma20"], cur["ma50"], cur["ma200"]
    rsi, atr          = cur["rsi"], cur["atr"]

    if any(pd.isna([ma20, ma50, ma200, rsi, atr])):
        base["reason"] = "지표 계산 중"
        return base

    indicators = {
        "ma20": float(ma20), "ma50": float(ma50), "ma200": float(ma200),
        "rsi": float(rsi), "atr": float(atr),
    }
    base["indicators"] = indicators

    # 1) 상승 추세
    cond_uptrend  = current_price > ma200
    cond_ma_align = ma50 > ma200
    # 2) 눌림목
    cond_pullback = current_price <= ma20 * (1 + config.MA_PULLBACK_TOLERANCE)
    # 3) RSI 구간
    cond_rsi      = config.RSI_BUY_MIN <= rsi <= config.RSI_BUY_MAX
    # 4) 반등 캔들 (현재 봉이 양봉이거나 직전 고가 돌파)
    cond_rebound  = (cur["close"] > prev["high"]) or (cur["close"] > cur["open"])

    checks = {
        "추세(P>MA200)":     cond_uptrend,
        "정렬(MA50>MA200)":  cond_ma_align,
        "눌림(P≤MA20·1.005)": cond_pullback,
        f"RSI∈[{config.RSI_BUY_MIN},{config.RSI_BUY_MAX}]": cond_rsi,
        "반등캔들":           cond_rebound,
    }

    if all(checks.values()):
        reason = (
            f"BUY ✓ 추세상승+눌림목+반등 "
            f"(P={current_price:,.0f}, MA20={ma20:,.0f}, MA50={ma50:,.0f}, "
            f"MA200={ma200:,.0f}, RSI={rsi:.1f}, ATR={atr:,.0f})"
        )
        return {"signal": "BUY", "reason": reason, "indicators": indicators}

    failed = [k for k, v in checks.items() if not v]
    base["reason"] = (
        f"BUY 보류 — 미충족: {', '.join(failed)} "
        f"(P={current_price:,.0f}, MA20={ma20:,.0f}, MA50={ma50:,.0f}, "
        f"MA200={ma200:,.0f}, RSI={rsi:.1f})"
    )
    return base


# ── 손절가 계산 ──────────────────────────────────────

def compute_stop_loss(entry_price: float, entry_atr: float) -> float:
    """
    손절가 = max(매수가 * (1 + MAX_STOP_LOSS), 매수가 - ATR_STOP_MULT * ATR)
    → 두 값 중 매수가에 더 가까운(=손실폭이 작은) 가격을 사용.
    """
    pct_stop = entry_price * (1 + config.MAX_STOP_LOSS)
    atr_stop = entry_price - config.ATR_STOP_MULT * entry_atr
    return max(pct_stop, atr_stop)


# ── 매도 판정 ────────────────────────────────────────

def evaluate_exit(position: dict, current_price: float, df: pd.DataFrame) -> dict:
    """
    포지션 보유 중 매도 판정.
    position: {
      entry_price, initial_volume, remaining_volume,
      entry_atr, stop_loss_price, highest_price,
      tp1_done, tp2_done
    }
    반환: {
      action: "STOP_LOSS" / "TP1" / "TP2" / "TRAILING_STOP" / "TREND_BREAK" / "HOLD",
      sell_ratio: 보유 잔량 대비 매도 비율 (0~1),
      reason: 사유,
      indicators: 현재 지표값
    }
    """
    out = {"action": "HOLD", "sell_ratio": 0.0, "reason": "", "indicators": {}}

    entry_price = position["entry_price"]
    pnl_pct     = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

    # MA50 계산 (추세 이탈 체크용)
    ma50 = None
    if not df.empty and len(df) >= config.MA_TREND_MID:
        ma50_series = df["close"].rolling(window=config.MA_TREND_MID).mean()
        if not pd.isna(ma50_series.iloc[-1]):
            ma50 = float(ma50_series.iloc[-1])
    out["indicators"] = {"ma50": ma50, "pnl_pct": pnl_pct}

    # 1) 손절 (최우선)
    if current_price <= position["stop_loss_price"]:
        return {
            "action": "STOP_LOSS",
            "sell_ratio": 1.0,
            "reason": (f"STOP_LOSS 매수가={entry_price:,.0f} 손절가={position['stop_loss_price']:,.0f} "
                       f"현재가={current_price:,.0f} ({pnl_pct*100:+.2f}%)"),
            "indicators": out["indicators"],
        }

    # 2) 1차 익절
    if not position.get("tp1_done") and pnl_pct >= config.TP1_PCT:
        return {
            "action": "TP1",
            "sell_ratio": config.TP1_RATIO,  # 잔량 대비가 아니라 "초기 수량 대비" — trader에서 환산
            "reason": f"TP1 +{pnl_pct*100:.2f}% (초기 {config.TP1_RATIO*100:.0f}% 매도)",
            "indicators": out["indicators"],
        }

    # 3) 2차 익절
    if (not position.get("tp2_done")) and position.get("tp1_done") and pnl_pct >= config.TP2_PCT:
        return {
            "action": "TP2",
            "sell_ratio": config.TP2_RATIO,
            "reason": f"TP2 +{pnl_pct*100:.2f}% (초기 {config.TP2_RATIO*100:.0f}% 매도)",
            "indicators": out["indicators"],
        }

    # 4) 트레일링 스탑 (TP1 이후, 잔여 물량 보호)
    if position.get("tp1_done"):
        highest = position.get("highest_price", entry_price)
        if highest > 0 and current_price <= highest * (1 - config.TRAILING_STOP_PCT):
            return {
                "action": "TRAILING_STOP",
                "sell_ratio": 1.0,
                "reason": (f"TRAILING_STOP 고점={highest:,.0f} 현재가={current_price:,.0f} "
                           f"({(current_price/highest - 1)*100:+.2f}%, 누적 {pnl_pct*100:+.2f}%)"),
                "indicators": out["indicators"],
            }

    # 5) 추세 이탈 (MA50 하향 이탈 → 잔여 전량 청산)
    if ma50 is not None and current_price < ma50:
        return {
            "action": "TREND_BREAK",
            "sell_ratio": 1.0,
            "reason": f"TREND_BREAK 현재가<MA50 ({current_price:,.0f}<{ma50:,.0f}, 누적 {pnl_pct*100:+.2f}%)",
            "indicators": out["indicators"],
        }

    out["reason"] = f"보유중 ({pnl_pct*100:+.2f}%)"
    return out


# ── 변동성 차단 ──────────────────────────────────────

def is_volatility_halt(df: pd.DataFrame) -> Optional[str]:
    """
    직전 1시간봉의 (고가-저가) 가 ATR * VOLATILITY_HALT_MULT 이상이면 차단 사유 반환.
    안전하면 None 반환.
    """
    if df.empty or len(df) < config.ATR_PERIOD + 2:
        return None
    atr_series = _atr(df, config.ATR_PERIOD)
    atr = atr_series.iloc[-2]  # 직전봉 기준 ATR
    if pd.isna(atr) or atr <= 0:
        return None
    last = df.iloc[-1]
    candle_range = last["high"] - last["low"]
    threshold = atr * config.VOLATILITY_HALT_MULT
    if candle_range >= threshold:
        return (f"변동성 급등: 직전봉 변동폭={candle_range:,.0f} ≥ ATR×{config.VOLATILITY_HALT_MULT}={threshold:,.0f}")
    return None

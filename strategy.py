"""
strategy.py — 이동평균선 + RSI 매매 전략
매수/매도 신호를 계산하여 반환합니다.
"""
import pandas as pd
import numpy as np
import config
from logger import get_logger

log = get_logger(__name__)


def calc_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """단기/장기 이동평균선 계산"""
    df = df.copy()
    df["ma_short"] = df["close"].rolling(window=config.MA_SHORT).mean()
    df["ma_long"]  = df["close"].rolling(window=config.MA_LONG).mean()
    return df


def calc_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """RSI 계산 (Wilder's smoothing)"""
    df = df.copy()
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/config.RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/config.RSI_PERIOD, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def get_signal(df: pd.DataFrame) -> dict:
    """
    매매 신호 계산
    반환:
      signal: "BUY" / "SELL" / "HOLD"
      reason: 신호 발생 이유
      ma_short, ma_long, rsi: 현재 지표값
    """
    if df.empty or len(df) < config.MA_LONG + 5:
        return {"signal": "HOLD", "reason": "데이터 부족", "ma_short": 0, "ma_long": 0, "rsi": 0}

    df = calc_moving_averages(df)
    df = calc_rsi(df)

    # 최신 2개 봉 (현재봉, 이전봉)
    cur  = df.iloc[-1]
    prev = df.iloc[-2]

    ma_short = cur["ma_short"]
    ma_long  = cur["ma_long"]
    rsi      = cur["rsi"]

    # NaN 체크
    if any(pd.isna([ma_short, ma_long, rsi])):
        return {"signal": "HOLD", "reason": "지표 계산 중", "ma_short": 0, "ma_long": 0, "rsi": 0}

    # ── 매수 신호 ─────────────────────────────────────
    # 조건 1: 골든크로스 (단기MA가 장기MA를 상향돌파)
    golden_cross = (prev["ma_short"] <= prev["ma_long"]) and (ma_short > ma_long)
    # 조건 2: RSI가 과매수 구간이 아님
    rsi_ok = rsi < config.RSI_OVERBOUGHT

    if golden_cross and rsi_ok:
        reason = f"골든크로스 (MA{config.MA_SHORT}={ma_short:,.0f} > MA{config.MA_LONG}={ma_long:,.0f}, RSI={rsi:.1f})"
        log.info(f"📈 매수 신호: {reason}")
        return {"signal": "BUY", "reason": reason, "ma_short": ma_short, "ma_long": ma_long, "rsi": rsi}

    # ── 매도 신호 ─────────────────────────────────────
    # 조건: 데드크로스 (단기MA가 장기MA를 하향돌파)
    dead_cross = (prev["ma_short"] >= prev["ma_long"]) and (ma_short < ma_long)

    if dead_cross:
        reason = f"데드크로스 (MA{config.MA_SHORT}={ma_short:,.0f} < MA{config.MA_LONG}={ma_long:,.0f}, RSI={rsi:.1f})"
        log.info(f"📉 매도 신호: {reason}")
        return {"signal": "SELL", "reason": reason, "ma_short": ma_short, "ma_long": ma_long, "rsi": rsi}

    # ── 보유 ─────────────────────────────────────────
    ma_status = "단기>장기" if ma_short > ma_long else "단기<장기"
    reason = f"신호 없음 ({ma_status}, RSI={rsi:.1f})"
    return {"signal": "HOLD", "reason": reason, "ma_short": ma_short, "ma_long": ma_long, "rsi": rsi}


def check_stop_take(avg_buy_price: float, current_price: float) -> dict:
    """
    손절/익절 조건 체크
    반환: {"action": "STOP_LOSS"/"TAKE_PROFIT"/"HOLD", "pnl_pct": 수익률}
    """
    if avg_buy_price <= 0:
        return {"action": "HOLD", "pnl_pct": 0.0}

    pnl_pct = (current_price - avg_buy_price) / avg_buy_price

    if pnl_pct <= config.STOP_LOSS:
        log.warning(f"🛑 손절 조건: 매수가={avg_buy_price:,.0f} 현재가={current_price:,.0f} ({pnl_pct*100:.2f}%)")
        return {"action": "STOP_LOSS", "pnl_pct": pnl_pct}

    if pnl_pct >= config.TAKE_PROFIT:
        log.info(f"🎯 익절 조건: 매수가={avg_buy_price:,.0f} 현재가={current_price:,.0f} ({pnl_pct*100:.2f}%)")
        return {"action": "TAKE_PROFIT", "pnl_pct": pnl_pct}

    return {"action": "HOLD", "pnl_pct": pnl_pct}

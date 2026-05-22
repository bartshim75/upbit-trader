"""
config.py — 전체 설정값 로드
.env 파일에서 읽어오며, 코드에 API 키를 절대 하드코딩하지 않습니다.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── 타임존 (모든 시각 기록/표시는 KST 기준) ───────────
KST = timezone(timedelta(hours=9))


# ── 환경변수 파서 (inline 주석/공백 안전 처리) ─────
def _clean(v: str) -> str:
    """값 문자열에서 inline '#' 주석과 양쪽 공백 제거."""
    if v is None:
        return ""
    return v.split("#", 1)[0].strip()


def env_str(key: str, default: str = "") -> str:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return _clean(raw) or default


def env_int(key: str, default: int) -> int:
    v = _clean(os.getenv(key, ""))
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def env_float(key: str, default: float) -> float:
    v = _clean(os.getenv(key, ""))
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def env_bool(key: str, default: bool) -> bool:
    v = _clean(os.getenv(key, ""))
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class MarketSettings:
    name: str
    TICKER: str
    BUDGET: int
    POSITION_PCT: float
    MIN_ORDER_KRW: int
    MAX_STOP_LOSS: float
    ATR_STOP_MULT: float
    TP1_PCT: float
    TP1_RATIO: float
    TP2_PCT: float
    TP2_RATIO: float
    TRAILING_STOP_PCT: float
    DAILY_LOSS_LIMIT_PCT: float
    MAX_CONSECUTIVE_STOPS: int
    MA_TREND_LONG: int
    MA_TREND_MID: int
    MA_PULLBACK: int
    MA_PULLBACK_TOLERANCE: float
    ENTRY_MID_MA_BUFFER_PCT: float
    ENTRY_PULLBACK_TOLERANCE: float
    ENTRY_RSI_MAX: float
    ENTRY_RANGE_LOOKBACK_BARS: int
    ENTRY_RANGE_MAX_POSITION: float
    TREND_BREAK_BUFFER_PCT: float
    TREND_BREAK_CONFIRM_BARS: int
    RSI_PERIOD: int
    RSI_BUY_MIN: float
    RSI_BUY_MAX: float
    ATR_PERIOD: int
    VOLATILITY_HALT_MULT: float
    BB_PERIOD: int
    BB_STD: float
    BB_TOL: float
    BB_RSI_MAX: float
    BB_ATR_STOP_MULT: float
    BB_MAX_HOLD_BARS: int
    BB_MA200_FLOOR: float
    REGIME_LOOKBACK_BARS: int
    REGIME_TREND_SLOPE_MIN: float
    REGIME_SIDEWAYS_BAND: float
    REGIME_BEAR_SLOPE_MAX: float
    CANDLE_UNIT: int
    CANDLE_COUNT: int
    SLIPPAGE_LIMIT_PCT: float
    API_ERROR_LIMIT: int
    STATUS_FILE: str
    POSITION_FILE: str
    POSITIONS_FILE: str   # fixed 모드 다중 포지션 리스트 파일
    BASELINE_FILE: str
    EXIT_STRATEGY: str    # "trailing" (기존) | "fixed" (+FIXED_TP_PCT 정액익절, 다중포지션)
    FIXED_TP_PCT: float
    FIXED_SL_PCT: float


# ── 업비트 API ──────────────────────────────────────
UPBIT_ACCESS_KEY = env_str("UPBIT_ACCESS_KEY")
UPBIT_SECRET_KEY = env_str("UPBIT_SECRET_KEY")

# ── 거래 대상 ────────────────────────────────────────
TICKER = env_str("BTC_TICKER", env_str("TICKER", "KRW-BTC"))

# ── 예산 / 포지션 사이징 ─────────────────────────────
BUDGET        = env_int  ("BUDGET",        1_000_000)
POSITION_PCT  = env_float("POSITION_PCT",  0.15)
MIN_ORDER_KRW = env_int  ("MIN_ORDER_KRW", 5_000)

# ── 손절 / 익절 ──────────────────────────────────────
MAX_STOP_LOSS = env_float("MAX_STOP_LOSS", -0.02)
ATR_STOP_MULT = env_float("ATR_STOP_MULT", 1.5)

TP1_PCT   = env_float("TP1_PCT",   0.015)
TP1_RATIO = env_float("TP1_RATIO", 0.50)
TP2_PCT   = env_float("TP2_PCT",   0.030)
TP2_RATIO = env_float("TP2_RATIO", 0.30)
TRAILING_STOP_PCT = env_float("TRAILING_STOP_PCT", 0.018)

# ── 매도 전략 모드 (글로벌 기본값, per-market 오버라이드 가능) ───
# "trailing" : 기존 동작 (TP1/TP2/트레일링/손절/추세이탈, 동시 1포지션)
# "fixed"    : +FIXED_TP_PCT 정액 익절만 (손절/트레일링 없음, 다중 포지션 허용)
EXIT_STRATEGY = env_str("EXIT_STRATEGY", "trailing")
FIXED_TP_PCT  = env_float("FIXED_TP_PCT", 0.03)
FIXED_SL_PCT  = env_float("FIXED_SL_PCT", -0.08)

# ── 일일 리스크 한도 ─────────────────────────────────
DAILY_LOSS_LIMIT_PCT  = env_float("DAILY_LOSS_LIMIT_PCT",  0.03)
MAX_CONSECUTIVE_STOPS = env_int  ("MAX_CONSECUTIVE_STOPS", 3)

# ── 추세/지표 파라미터 (1시간봉) ───────────────────
MA_TREND_LONG = 200
MA_TREND_MID  = 50
MA_PULLBACK   = 20
MA_PULLBACK_TOLERANCE = 0.005
ENTRY_MID_MA_BUFFER_PCT = env_float("ENTRY_MID_MA_BUFFER_PCT", 0.0)
ENTRY_PULLBACK_TOLERANCE = env_float("ENTRY_PULLBACK_TOLERANCE", MA_PULLBACK_TOLERANCE)
ENTRY_RANGE_LOOKBACK_BARS = env_int("ENTRY_RANGE_LOOKBACK_BARS", 0)
ENTRY_RANGE_MAX_POSITION = env_float("ENTRY_RANGE_MAX_POSITION", 1.0)
TREND_BREAK_BUFFER_PCT = env_float("TREND_BREAK_BUFFER_PCT", 0.0)
TREND_BREAK_CONFIRM_BARS = env_int("TREND_BREAK_CONFIRM_BARS", 1)

RSI_PERIOD   = 14
RSI_BUY_MIN  = 30
RSI_BUY_MAX  = 55
ENTRY_RSI_MAX = env_float("ENTRY_RSI_MAX", RSI_BUY_MAX)

ATR_PERIOD = 14
VOLATILITY_HALT_MULT = 3.0

# ── 평균회귀 전략 (BB 하단, 횡보장용) ─────────────────
BB_PERIOD          = env_int  ("BB_PERIOD",          20)
BB_STD             = env_float("BB_STD",             2.0)
BB_TOL             = env_float("BB_TOL",             0.005)   # 저가가 하단 +0.5% 안 터치 시 허용
BB_RSI_MAX         = env_float("BB_RSI_MAX",         45.0)
BB_ATR_STOP_MULT   = env_float("BB_ATR_STOP_MULT",   3.0)
BB_MAX_HOLD_BARS   = env_int  ("BB_MAX_HOLD_BARS",   48)      # 시간 만료 (시간봉 기준)
BB_MA200_FLOOR     = env_float("BB_MA200_FLOOR",     0.85)    # P > MA200*0.85 (대폭락 회피)

# ── Regime 감지 (매수 평가 시점) ──────────────────────
REGIME_LOOKBACK_BARS    = env_int  ("REGIME_LOOKBACK_BARS",    50)
REGIME_TREND_SLOPE_MIN  = env_float("REGIME_TREND_SLOPE_MIN",  0.005)  # MA200 lookback 대비 +0.5% 이상이면 TREND
REGIME_SIDEWAYS_BAND    = env_float("REGIME_SIDEWAYS_BAND",    0.05)   # P가 MA200 ±5% 안이면 SIDEWAYS 후보
REGIME_BEAR_SLOPE_MAX   = env_float("REGIME_BEAR_SLOPE_MAX",   0.005)  # slope < -0.5%면 BEAR 처리

# ── 캔들 / API ───────────────────────────────────────
CANDLE_UNIT  = 60
CANDLE_COUNT = 250
SLIPPAGE_LIMIT_PCT = env_float("SLIPPAGE_LIMIT_PCT", 0.005)
API_ERROR_LIMIT    = env_int  ("API_ERROR_LIMIT",    3)

# ── 매매 주기 ────────────────────────────────────────
# 매수 평가는 항상 매 정시(:00) 1회. 포지션 보유 중에만 손절/TP/트레일링을 분 단위로 추가 체크.
EXIT_CHECK_INTERVAL_MIN = env_int("EXIT_CHECK_INTERVAL_MIN", 1)

# ── 파일 경로 ────────────────────────────────────────
TRADES_FILE    = "trades.csv"
STATUS_FILE    = "status.json"
POSITION_FILE  = "position.json"      # trailing 모드: 단일 포지션 dict
POSITIONS_FILE = "positions.json"     # fixed 모드: 다중 포지션 list
BASELINE_FILE  = "baseline.json"
LOG_FILE       = "trader.log"

# ── BTC 매도 전략 오버라이드 ─────────────────────────
BTC_EXIT_STRATEGY = env_str  ("BTC_EXIT_STRATEGY", EXIT_STRATEGY)
BTC_FIXED_TP_PCT  = env_float("BTC_FIXED_TP_PCT",  FIXED_TP_PCT)
BTC_FIXED_SL_PCT  = env_float("BTC_FIXED_SL_PCT",  FIXED_SL_PCT)


def _ticker_suffix(ticker: str) -> str:
    return ticker.replace("-", "_").replace("/", "_")


def _primary_market() -> MarketSettings:
    return MarketSettings(
        name="BTC",
        TICKER=TICKER,
        BUDGET=BUDGET,
        POSITION_PCT=POSITION_PCT,
        MIN_ORDER_KRW=MIN_ORDER_KRW,
        MAX_STOP_LOSS=MAX_STOP_LOSS,
        ATR_STOP_MULT=ATR_STOP_MULT,
        TP1_PCT=TP1_PCT,
        TP1_RATIO=TP1_RATIO,
        TP2_PCT=TP2_PCT,
        TP2_RATIO=TP2_RATIO,
        TRAILING_STOP_PCT=TRAILING_STOP_PCT,
        DAILY_LOSS_LIMIT_PCT=DAILY_LOSS_LIMIT_PCT,
        MAX_CONSECUTIVE_STOPS=MAX_CONSECUTIVE_STOPS,
        MA_TREND_LONG=MA_TREND_LONG,
        MA_TREND_MID=MA_TREND_MID,
        MA_PULLBACK=MA_PULLBACK,
        MA_PULLBACK_TOLERANCE=MA_PULLBACK_TOLERANCE,
        ENTRY_MID_MA_BUFFER_PCT=ENTRY_MID_MA_BUFFER_PCT,
        ENTRY_PULLBACK_TOLERANCE=ENTRY_PULLBACK_TOLERANCE,
        ENTRY_RSI_MAX=ENTRY_RSI_MAX,
        ENTRY_RANGE_LOOKBACK_BARS=ENTRY_RANGE_LOOKBACK_BARS,
        ENTRY_RANGE_MAX_POSITION=ENTRY_RANGE_MAX_POSITION,
        TREND_BREAK_BUFFER_PCT=TREND_BREAK_BUFFER_PCT,
        TREND_BREAK_CONFIRM_BARS=TREND_BREAK_CONFIRM_BARS,
        RSI_PERIOD=RSI_PERIOD,
        RSI_BUY_MIN=RSI_BUY_MIN,
        RSI_BUY_MAX=RSI_BUY_MAX,
        ATR_PERIOD=ATR_PERIOD,
        VOLATILITY_HALT_MULT=VOLATILITY_HALT_MULT,
        BB_PERIOD=BB_PERIOD,
        BB_STD=BB_STD,
        BB_TOL=BB_TOL,
        BB_RSI_MAX=BB_RSI_MAX,
        BB_ATR_STOP_MULT=BB_ATR_STOP_MULT,
        BB_MAX_HOLD_BARS=BB_MAX_HOLD_BARS,
        BB_MA200_FLOOR=BB_MA200_FLOOR,
        REGIME_LOOKBACK_BARS=REGIME_LOOKBACK_BARS,
        REGIME_TREND_SLOPE_MIN=REGIME_TREND_SLOPE_MIN,
        REGIME_SIDEWAYS_BAND=REGIME_SIDEWAYS_BAND,
        REGIME_BEAR_SLOPE_MAX=REGIME_BEAR_SLOPE_MAX,
        CANDLE_UNIT=CANDLE_UNIT,
        CANDLE_COUNT=CANDLE_COUNT,
        SLIPPAGE_LIMIT_PCT=SLIPPAGE_LIMIT_PCT,
        API_ERROR_LIMIT=API_ERROR_LIMIT,
        STATUS_FILE=STATUS_FILE,
        POSITION_FILE=POSITION_FILE,
        POSITIONS_FILE=POSITIONS_FILE,
        BASELINE_FILE=BASELINE_FILE,
        EXIT_STRATEGY=BTC_EXIT_STRATEGY,
        FIXED_TP_PCT=BTC_FIXED_TP_PCT,
        FIXED_SL_PCT=BTC_FIXED_SL_PCT,
    )


def primary_market() -> MarketSettings:
    return _primary_market()


# ── 추가 종목: DOGE (최근 90일 ETH 대비 상대 추세 우위 기준) ───────
ENABLE_DOGE = env_bool("ENABLE_DOGE", True)
DOGE_TICKER = env_str("DOGE_TICKER", "KRW-DOGE")

DOGE_BUDGET        = env_int  ("DOGE_BUDGET",        300_000)
DOGE_POSITION_PCT  = env_float("DOGE_POSITION_PCT",  0.12)
DOGE_MIN_ORDER_KRW = env_int  ("DOGE_MIN_ORDER_KRW", MIN_ORDER_KRW)

DOGE_MAX_STOP_LOSS = env_float("DOGE_MAX_STOP_LOSS", -0.025)
DOGE_ATR_STOP_MULT = env_float("DOGE_ATR_STOP_MULT", 2.0)
DOGE_TP1_PCT       = env_float("DOGE_TP1_PCT",       0.020)
DOGE_TP1_RATIO     = env_float("DOGE_TP1_RATIO",     0.45)
DOGE_TP2_PCT       = env_float("DOGE_TP2_PCT",       0.045)
DOGE_TP2_RATIO     = env_float("DOGE_TP2_RATIO",     0.30)
DOGE_TRAILING_STOP_PCT = env_float("DOGE_TRAILING_STOP_PCT", 0.025)

DOGE_DAILY_LOSS_LIMIT_PCT  = env_float("DOGE_DAILY_LOSS_LIMIT_PCT",  0.035)
DOGE_MAX_CONSECUTIVE_STOPS = env_int  ("DOGE_MAX_CONSECUTIVE_STOPS", 2)

# DOGE는 변동성이 커서 BTC보다 빠른 1H 추세/눌림 감지와 넓은 허용폭을 사용한다.
DOGE_MA_TREND_LONG = env_int  ("DOGE_MA_TREND_LONG", 160)
DOGE_MA_TREND_MID  = env_int  ("DOGE_MA_TREND_MID",  34)
DOGE_MA_PULLBACK   = env_int  ("DOGE_MA_PULLBACK",   12)
DOGE_MA_PULLBACK_TOLERANCE = env_float("DOGE_MA_PULLBACK_TOLERANCE", 0.0)
DOGE_ENTRY_MID_MA_BUFFER_PCT = env_float("DOGE_ENTRY_MID_MA_BUFFER_PCT", 0.010)
DOGE_ENTRY_PULLBACK_TOLERANCE = env_float("DOGE_ENTRY_PULLBACK_TOLERANCE", 0.0)
DOGE_ENTRY_RANGE_LOOKBACK_BARS = env_int("DOGE_ENTRY_RANGE_LOOKBACK_BARS", 24)
DOGE_ENTRY_RANGE_MAX_POSITION = env_float("DOGE_ENTRY_RANGE_MAX_POSITION", 0.65)
DOGE_TREND_BREAK_BUFFER_PCT = env_float("DOGE_TREND_BREAK_BUFFER_PCT", 0.012)
DOGE_TREND_BREAK_CONFIRM_BARS = env_int("DOGE_TREND_BREAK_CONFIRM_BARS", 2)

DOGE_RSI_PERIOD  = env_int  ("DOGE_RSI_PERIOD",  14)
DOGE_RSI_BUY_MIN = env_float("DOGE_RSI_BUY_MIN", 35)
DOGE_RSI_BUY_MAX = env_float("DOGE_RSI_BUY_MAX", 55)
DOGE_ENTRY_RSI_MAX = env_float("DOGE_ENTRY_RSI_MAX", 55)

DOGE_ATR_PERIOD = env_int  ("DOGE_ATR_PERIOD", 14)
DOGE_VOLATILITY_HALT_MULT = env_float("DOGE_VOLATILITY_HALT_MULT", 3.5)

DOGE_BB_PERIOD        = env_int  ("DOGE_BB_PERIOD",        20)
DOGE_BB_STD           = env_float("DOGE_BB_STD",           2.2)
DOGE_BB_TOL           = env_float("DOGE_BB_TOL",           0.012)
DOGE_BB_RSI_MAX       = env_float("DOGE_BB_RSI_MAX",       50.0)
DOGE_BB_ATR_STOP_MULT = env_float("DOGE_BB_ATR_STOP_MULT", 3.2)
DOGE_BB_MAX_HOLD_BARS = env_int  ("DOGE_BB_MAX_HOLD_BARS", 36)
DOGE_BB_MA200_FLOOR   = env_float("DOGE_BB_MA200_FLOOR",   0.82)

DOGE_REGIME_LOOKBACK_BARS   = env_int  ("DOGE_REGIME_LOOKBACK_BARS",   36)
DOGE_REGIME_TREND_SLOPE_MIN = env_float("DOGE_REGIME_TREND_SLOPE_MIN", 0.008)
DOGE_REGIME_SIDEWAYS_BAND   = env_float("DOGE_REGIME_SIDEWAYS_BAND",   0.08)
DOGE_REGIME_BEAR_SLOPE_MAX  = env_float("DOGE_REGIME_BEAR_SLOPE_MAX",  0.008)

DOGE_CANDLE_UNIT  = CANDLE_UNIT
DOGE_CANDLE_COUNT = env_int("DOGE_CANDLE_COUNT", 250)
DOGE_SLIPPAGE_LIMIT_PCT = env_float("DOGE_SLIPPAGE_LIMIT_PCT", 0.008)
DOGE_API_ERROR_LIMIT = API_ERROR_LIMIT

DOGE_EXIT_STRATEGY = env_str  ("DOGE_EXIT_STRATEGY", EXIT_STRATEGY)
DOGE_FIXED_TP_PCT  = env_float("DOGE_FIXED_TP_PCT",  FIXED_TP_PCT)
DOGE_FIXED_SL_PCT  = env_float("DOGE_FIXED_SL_PCT",  FIXED_SL_PCT)


def _doge_market() -> MarketSettings:
    suffix = _ticker_suffix(DOGE_TICKER)
    return MarketSettings(
        name="DOGE",
        TICKER=DOGE_TICKER,
        BUDGET=DOGE_BUDGET,
        POSITION_PCT=DOGE_POSITION_PCT,
        MIN_ORDER_KRW=DOGE_MIN_ORDER_KRW,
        MAX_STOP_LOSS=DOGE_MAX_STOP_LOSS,
        ATR_STOP_MULT=DOGE_ATR_STOP_MULT,
        TP1_PCT=DOGE_TP1_PCT,
        TP1_RATIO=DOGE_TP1_RATIO,
        TP2_PCT=DOGE_TP2_PCT,
        TP2_RATIO=DOGE_TP2_RATIO,
        TRAILING_STOP_PCT=DOGE_TRAILING_STOP_PCT,
        DAILY_LOSS_LIMIT_PCT=DOGE_DAILY_LOSS_LIMIT_PCT,
        MAX_CONSECUTIVE_STOPS=DOGE_MAX_CONSECUTIVE_STOPS,
        MA_TREND_LONG=DOGE_MA_TREND_LONG,
        MA_TREND_MID=DOGE_MA_TREND_MID,
        MA_PULLBACK=DOGE_MA_PULLBACK,
        MA_PULLBACK_TOLERANCE=DOGE_MA_PULLBACK_TOLERANCE,
        ENTRY_MID_MA_BUFFER_PCT=DOGE_ENTRY_MID_MA_BUFFER_PCT,
        ENTRY_PULLBACK_TOLERANCE=DOGE_ENTRY_PULLBACK_TOLERANCE,
        ENTRY_RSI_MAX=DOGE_ENTRY_RSI_MAX,
        ENTRY_RANGE_LOOKBACK_BARS=DOGE_ENTRY_RANGE_LOOKBACK_BARS,
        ENTRY_RANGE_MAX_POSITION=DOGE_ENTRY_RANGE_MAX_POSITION,
        TREND_BREAK_BUFFER_PCT=DOGE_TREND_BREAK_BUFFER_PCT,
        TREND_BREAK_CONFIRM_BARS=DOGE_TREND_BREAK_CONFIRM_BARS,
        RSI_PERIOD=DOGE_RSI_PERIOD,
        RSI_BUY_MIN=DOGE_RSI_BUY_MIN,
        RSI_BUY_MAX=DOGE_RSI_BUY_MAX,
        ATR_PERIOD=DOGE_ATR_PERIOD,
        VOLATILITY_HALT_MULT=DOGE_VOLATILITY_HALT_MULT,
        BB_PERIOD=DOGE_BB_PERIOD,
        BB_STD=DOGE_BB_STD,
        BB_TOL=DOGE_BB_TOL,
        BB_RSI_MAX=DOGE_BB_RSI_MAX,
        BB_ATR_STOP_MULT=DOGE_BB_ATR_STOP_MULT,
        BB_MAX_HOLD_BARS=DOGE_BB_MAX_HOLD_BARS,
        BB_MA200_FLOOR=DOGE_BB_MA200_FLOOR,
        REGIME_LOOKBACK_BARS=DOGE_REGIME_LOOKBACK_BARS,
        REGIME_TREND_SLOPE_MIN=DOGE_REGIME_TREND_SLOPE_MIN,
        REGIME_SIDEWAYS_BAND=DOGE_REGIME_SIDEWAYS_BAND,
        REGIME_BEAR_SLOPE_MAX=DOGE_REGIME_BEAR_SLOPE_MAX,
        CANDLE_UNIT=DOGE_CANDLE_UNIT,
        CANDLE_COUNT=DOGE_CANDLE_COUNT,
        SLIPPAGE_LIMIT_PCT=DOGE_SLIPPAGE_LIMIT_PCT,
        API_ERROR_LIMIT=DOGE_API_ERROR_LIMIT,
        STATUS_FILE=f"status_{suffix}.json",
        POSITION_FILE=f"position_{suffix}.json",
        POSITIONS_FILE=f"positions_{suffix}.json",
        BASELINE_FILE=f"baseline_{suffix}.json",
        EXIT_STRATEGY=DOGE_EXIT_STRATEGY,
        FIXED_TP_PCT=DOGE_FIXED_TP_PCT,
        FIXED_SL_PCT=DOGE_FIXED_SL_PCT,
    )


def active_markets() -> list[MarketSettings]:
    markets = [_primary_market()]
    if ENABLE_DOGE:
        markets.append(_doge_market())
    return markets


def market_by_ticker(ticker: str) -> MarketSettings:
    for market in active_markets():
        if market.TICKER == ticker:
            return market
    raise ValueError(f"활성 거래 대상이 아닙니다: {ticker}")

# ── 대시보드 ───────────────────────────────────────
DASHBOARD_PASSWORD     = env_str("DASHBOARD_PASSWORD", "")
DASHBOARD_PORT         = env_int("DASHBOARD_PORT", 8501)
DASHBOARD_REFRESH_SEC  = env_int("DASHBOARD_REFRESH_SEC", 60)
DASHBOARD_CACHE_TTL_SEC = env_int("DASHBOARD_CACHE_TTL_SEC", 60)


def _validate_market(market: MarketSettings):
    if not market.TICKER.startswith("KRW-"):
        raise ValueError(f"❌ {market.name}: 원화 마켓만 지원합니다. ({market.TICKER})")
    if market.MAX_STOP_LOSS >= 0:
        raise ValueError(f"❌ {market.name}: MAX_STOP_LOSS는 음수여야 합니다. (예: -0.02)")
    if not (0 < market.POSITION_PCT <= 1):
        raise ValueError(f"❌ {market.name}: POSITION_PCT는 0~1 사이여야 합니다.")
    if market.ENTRY_MID_MA_BUFFER_PCT < 0 or market.ENTRY_PULLBACK_TOLERANCE < 0:
        raise ValueError(f"❌ {market.name}: 진입 버퍼/눌림 허용폭은 0 이상이어야 합니다.")
    if market.ENTRY_RSI_MAX < market.RSI_BUY_MIN:
        raise ValueError(f"❌ {market.name}: ENTRY_RSI_MAX는 RSI_BUY_MIN 이상이어야 합니다.")
    if market.ENTRY_RANGE_LOOKBACK_BARS < 0:
        raise ValueError(f"❌ {market.name}: ENTRY_RANGE_LOOKBACK_BARS는 0 이상이어야 합니다.")
    if not (0 < market.ENTRY_RANGE_MAX_POSITION <= 1):
        raise ValueError(f"❌ {market.name}: ENTRY_RANGE_MAX_POSITION은 0~1 사이여야 합니다.")
    if market.TREND_BREAK_BUFFER_PCT < 0:
        raise ValueError(f"❌ {market.name}: TREND_BREAK_BUFFER_PCT는 0 이상이어야 합니다.")
    if market.TREND_BREAK_CONFIRM_BARS < 1:
        raise ValueError(f"❌ {market.name}: TREND_BREAK_CONFIRM_BARS는 1 이상이어야 합니다.")
    if market.TP1_RATIO + market.TP2_RATIO >= 1.0:
        raise ValueError(f"❌ {market.name}: TP1_RATIO + TP2_RATIO < 1 이어야 트레일링 잔여 물량이 남습니다.")
    if market.BUDGET < market.MIN_ORDER_KRW:
        raise ValueError(f"❌ {market.name}: BUDGET은 MIN_ORDER_KRW 이상이어야 합니다.")
    if market.EXIT_STRATEGY not in ("trailing", "fixed"):
        raise ValueError(f"❌ {market.name}: EXIT_STRATEGY는 'trailing' 또는 'fixed' 여야 합니다. (현재: {market.EXIT_STRATEGY})")
    if market.FIXED_TP_PCT <= 0:
        raise ValueError(f"❌ {market.name}: FIXED_TP_PCT는 0보다 커야 합니다. (현재: {market.FIXED_TP_PCT})")
    if market.FIXED_SL_PCT >= 0:
        raise ValueError(f"❌ {market.name}: FIXED_SL_PCT는 음수여야 합니다. (현재: {market.FIXED_SL_PCT})")


def validate():
    if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
        raise ValueError("❌ .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 없습니다.")
    seen = set()
    for market in active_markets():
        if market.TICKER in seen:
            raise ValueError(f"❌ 거래 대상 중복: {market.TICKER}")
        seen.add(market.TICKER)
        _validate_market(market)

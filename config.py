"""
config.py — 전체 설정값 로드
.env 파일에서 읽어오며, 코드에 API 키를 절대 하드코딩하지 않습니다.
"""
import os
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


# ── 업비트 API ──────────────────────────────────────
UPBIT_ACCESS_KEY = env_str("UPBIT_ACCESS_KEY")
UPBIT_SECRET_KEY = env_str("UPBIT_SECRET_KEY")

# ── 거래 대상 ────────────────────────────────────────
TICKER = env_str("TICKER", "KRW-BTC")

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

# ── 일일 리스크 한도 ─────────────────────────────────
DAILY_LOSS_LIMIT_PCT  = env_float("DAILY_LOSS_LIMIT_PCT",  0.03)
MAX_CONSECUTIVE_STOPS = env_int  ("MAX_CONSECUTIVE_STOPS", 3)

# ── 추세/지표 파라미터 (1시간봉) ───────────────────
MA_TREND_LONG = 200
MA_TREND_MID  = 50
MA_PULLBACK   = 20
MA_PULLBACK_TOLERANCE = 0.005

RSI_PERIOD   = 14
RSI_BUY_MIN  = 30
RSI_BUY_MAX  = 55

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
TRADES_FILE   = "trades.csv"
STATUS_FILE   = "status.json"
POSITION_FILE = "position.json"
BASELINE_FILE = "baseline.json"
LOG_FILE      = "trader.log"

# ── 대시보드 ───────────────────────────────────────
DASHBOARD_PASSWORD     = env_str("DASHBOARD_PASSWORD", "")
DASHBOARD_PORT         = env_int("DASHBOARD_PORT", 8501)
DASHBOARD_REFRESH_SEC  = env_int("DASHBOARD_REFRESH_SEC", 60)
DASHBOARD_CACHE_TTL_SEC = env_int("DASHBOARD_CACHE_TTL_SEC", 60)


def validate():
    if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
        raise ValueError("❌ .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 없습니다.")
    if MAX_STOP_LOSS >= 0:
        raise ValueError("❌ MAX_STOP_LOSS는 음수여야 합니다. (예: -0.02)")
    if not (0 < POSITION_PCT <= 1):
        raise ValueError("❌ POSITION_PCT는 0~1 사이여야 합니다.")
    if TP1_RATIO + TP2_RATIO >= 1.0:
        raise ValueError("❌ TP1_RATIO + TP2_RATIO < 1 이어야 트레일링 잔여 물량이 남습니다.")

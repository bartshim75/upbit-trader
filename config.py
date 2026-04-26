"""
config.py — 전체 설정값 로드
.env 파일에서 읽어오며, 코드에 API 키를 절대 하드코딩하지 않습니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()


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
TRAILING_STOP_PCT = env_float("TRAILING_STOP_PCT", 0.012)

# ── 일일 리스크 한도 ─────────────────────────────────
DAILY_LOSS_LIMIT_PCT  = env_float("DAILY_LOSS_LIMIT_PCT",  0.03)
MAX_CONSECUTIVE_STOPS = env_int  ("MAX_CONSECUTIVE_STOPS", 3)

# ── 추세/지표 파라미터 (1시간봉) ───────────────────
MA_TREND_LONG = 200
MA_TREND_MID  = 50
MA_PULLBACK   = 20
MA_PULLBACK_TOLERANCE = 0.005

RSI_PERIOD   = 14
RSI_BUY_MIN  = 35
RSI_BUY_MAX  = 50

ATR_PERIOD = 14
VOLATILITY_HALT_MULT = 3.0

# ── 캔들 / API ───────────────────────────────────────
CANDLE_UNIT  = 60
CANDLE_COUNT = 250
SLIPPAGE_LIMIT_PCT = env_float("SLIPPAGE_LIMIT_PCT", 0.005)
API_ERROR_LIMIT    = env_int  ("API_ERROR_LIMIT",    3)

# ── 파일 경로 ────────────────────────────────────────
TRADES_FILE   = "trades.csv"
STATUS_FILE   = "status.json"
POSITION_FILE = "position.json"
BASELINE_FILE = "baseline.json"
LOG_FILE      = "trader.log"

# ── 대시보드 ───────────────────────────────────────
DASHBOARD_PASSWORD = env_str("DASHBOARD_PASSWORD", "")
DASHBOARD_PORT     = env_int("DASHBOARD_PORT", 8501)


def validate():
    if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
        raise ValueError("❌ .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 없습니다.")
    if MAX_STOP_LOSS >= 0:
        raise ValueError("❌ MAX_STOP_LOSS는 음수여야 합니다. (예: -0.02)")
    if not (0 < POSITION_PCT <= 1):
        raise ValueError("❌ POSITION_PCT는 0~1 사이여야 합니다.")
    if TP1_RATIO + TP2_RATIO >= 1.0:
        raise ValueError("❌ TP1_RATIO + TP2_RATIO < 1 이어야 트레일링 잔여 물량이 남습니다.")

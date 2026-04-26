"""
config.py — 전체 설정값 로드
.env 파일에서 읽어오며, 코드에 API 키를 절대 하드코딩하지 않습니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 업비트 API ──────────────────────────────────────
UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

# ── 거래 대상 ────────────────────────────────────────
TICKER = os.getenv("TICKER", "KRW-BTC")

# ── 예산 / 포지션 사이징 ─────────────────────────────
BUDGET = int(os.getenv("BUDGET", 1_000_000))            # 총 배정 예산 (원)
POSITION_PCT = float(os.getenv("POSITION_PCT", 0.15))   # 1회 진입 = 유효예산의 15%
MIN_ORDER_KRW = int(os.getenv("MIN_ORDER_KRW", 5_000))  # 업비트 최소 주문 금액

# ── 손절 / 익절 ──────────────────────────────────────
MAX_STOP_LOSS = float(os.getenv("MAX_STOP_LOSS", -0.02))  # 손절 한도 -2%
ATR_STOP_MULT = float(os.getenv("ATR_STOP_MULT", 1.5))    # ATR * 1.5 손절 (한도 내에서)

TP1_PCT   = float(os.getenv("TP1_PCT",   0.015))  # 1차 익절 +1.5%
TP1_RATIO = float(os.getenv("TP1_RATIO", 0.50))   # 1차 매도 비율 50%
TP2_PCT   = float(os.getenv("TP2_PCT",   0.030))  # 2차 익절 +3.0%
TP2_RATIO = float(os.getenv("TP2_RATIO", 0.30))   # 2차 매도 비율 30%
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", 0.012))  # 잔여 물량 트레일링 -1.2%

# ── 일일 리스크 한도 ─────────────────────────────────
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", 0.03))  # 일일 손실 -3%
MAX_CONSECUTIVE_STOPS = int(os.getenv("MAX_CONSECUTIVE_STOPS", 3))     # 연속 손절 3회면 당일 정지

# ── 추세/지표 파라미터 (1시간봉) ───────────────────
MA_TREND_LONG = 200   # 상승추세 필터
MA_TREND_MID  = 50    # 추세 보조 필터, 잔여 익절 청산 기준
MA_PULLBACK   = 20    # 눌림목 매수 기준선
MA_PULLBACK_TOLERANCE = 0.005  # MA20 + 0.5% 이내까지 눌림 허용

RSI_PERIOD   = 14
RSI_BUY_MIN  = 35     # 매수 RSI 하한 (너무 약한 반등 제외)
RSI_BUY_MAX  = 50     # 매수 RSI 상한 (과열 진입 방지)

ATR_PERIOD = 14
VOLATILITY_HALT_MULT = 3.0  # 직전봉 변동폭이 ATR * 3 이상이면 거래 일시정지

# ── 캔들 / API ───────────────────────────────────────
CANDLE_UNIT = 60       # 1시간봉
CANDLE_COUNT = 250     # MA200 계산을 위해 250봉
SLIPPAGE_LIMIT_PCT = float(os.getenv("SLIPPAGE_LIMIT_PCT", 0.005))  # 시장가 예상 체결가 0.5% 이상 불리하면 취소
API_ERROR_LIMIT = int(os.getenv("API_ERROR_LIMIT", 3))              # 연속 API 오류 3회면 사이클 중단

# ── 파일 경로 ────────────────────────────────────────
TRADES_FILE   = "trades.csv"
STATUS_FILE   = "status.json"
POSITION_FILE = "position.json"
LOG_FILE      = "trader.log"


def validate():
    if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
        raise ValueError("❌ .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 없습니다.")
    if MAX_STOP_LOSS >= 0:
        raise ValueError("❌ MAX_STOP_LOSS는 음수여야 합니다. (예: -0.02)")
    if not (0 < POSITION_PCT <= 1):
        raise ValueError("❌ POSITION_PCT는 0~1 사이여야 합니다.")
    if TP1_RATIO + TP2_RATIO >= 1.0:
        raise ValueError("❌ TP1_RATIO + TP2_RATIO < 1 이어야 트레일링 잔여 물량이 남습니다.")

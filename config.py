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

# ── 예산 설정 ────────────────────────────────────────
BUDGET       = int(os.getenv("BUDGET",       1_000_000))  # 총 배정 예산 (원)
ORDER_AMOUNT = int(os.getenv("ORDER_AMOUNT",   100_000))  # 1회 매수 금액 (원)

# ── 매매 전략 ────────────────────────────────────────
STOP_LOSS    = float(os.getenv("STOP_LOSS",   -0.02))     # 손절선 -2%
TAKE_PROFIT  = float(os.getenv("TAKE_PROFIT",  0.03))     # 익절선 +3%

# ── 이동평균선 파라미터 ──────────────────────────────
MA_SHORT  = 7    # 단기 이동평균 (7봉)
MA_LONG   = 25   # 장기 이동평균 (25봉)
RSI_PERIOD = 14  # RSI 기간
RSI_OVERBOUGHT = 70   # RSI 과매수 기준 (이 이상이면 매수 안 함)
RSI_OVERSOLD   = 30   # RSI 과매도 기준 (참고용)

# ── 캔들 기준 ────────────────────────────────────────
CANDLE_UNIT = 60   # 1시간봉 (분 단위)
CANDLE_COUNT = 100 # 분석에 사용할 캔들 수

# ── 파일 경로 ────────────────────────────────────────
TRADES_FILE = "trades.csv"
STATUS_FILE = "status.json"
LOG_FILE    = "trader.log"

# ── 유효성 검사 ──────────────────────────────────────
def validate():
    if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
        raise ValueError("❌ .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 없습니다.")
    if ORDER_AMOUNT > BUDGET:
        raise ValueError("❌ 1회 매수금액이 배정 예산보다 큽니다.")
    if STOP_LOSS >= 0:
        raise ValueError("❌ 손절선은 음수여야 합니다. (예: -0.02)")
    if TAKE_PROFIT <= 0:
        raise ValueError("❌ 익절선은 양수여야 합니다. (예: 0.03)")

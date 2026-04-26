"""
reset_baseline.py — baseline 수동 재설정 스크립트

사용법:
  python reset_baseline.py            # 현재 거래소 잔고를 baseline으로 (= 기존 자산 보호)
  python reset_baseline.py --zero     # baseline을 0으로 (= 모든 BTC를 봇이 운용 가능하게)
  python reset_baseline.py --show     # 현재 baseline 확인만

⚠ 봇을 정지한 상태에서 실행하세요:
   sudo systemctl stop upbit-trader
"""
import sys
import config
import upbit_api as api
from budget_manager import BudgetManager


def main():
    args = sys.argv[1:]

    bm = BudgetManager()

    if "--show" in args:
        b = bm.load_baseline()
        if b is None:
            print("baseline.json 없음 (봇 첫 실행 시 자동 기록됨)")
        else:
            print(f"baseline 수량: {b['volume']:.8f}")
            print(f"기록 시각:    {b.get('recorded_at')}")
            print(f"메모:        {b.get('note', '-')}")
        return

    if "--zero" in args:
        bm.save_baseline(0.0, note="수동 재설정 (--zero): 모든 BTC를 봇이 운용 가능")
        print("✅ baseline = 0 으로 설정. 거래소의 모든 BTC를 봇이 매도 가능합니다.")
        print("⚠ 주의: 다음 사이클에서 기존 보유분이 봇 전략에 따라 매도될 수 있습니다.")
        return

    # 기본: 현재 잔고로 재설정
    upbit = api.get_upbit_client()
    coin = api.get_coin_balance(upbit, config.TICKER)
    cur_vol = coin["balance"]
    bm.save_baseline(cur_vol, note=f"수동 재설정: {config.TICKER} 잔고 {cur_vol:.8f} 보호")
    print(f"✅ baseline = {cur_vol:.8f} 으로 설정 (현재 거래소 잔고).")
    print("   이 수량은 봇이 절대 매도하지 않습니다.")


if __name__ == "__main__":
    main()

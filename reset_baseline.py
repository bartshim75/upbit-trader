"""
reset_baseline.py — baseline 수동 재설정 스크립트

사용법:
  python reset_baseline.py                         # 활성 종목 현재 잔고를 baseline으로 (= 기존 자산 보호)
  python reset_baseline.py --ticker KRW-DOGE       # 특정 종목만 재설정
  python reset_baseline.py --zero                  # baseline을 0으로 (= 봇이 전체 수량 운용 가능)
  python reset_baseline.py --show                  # 현재 baseline 확인만

⚠ 봇을 정지한 상태에서 실행하세요:
   sudo systemctl stop upbit-trader
"""
import sys
import config
from budget_manager import BudgetManager


def _selected_markets(args: list[str]):
    if "--ticker" not in args:
        return config.active_markets()
    idx = args.index("--ticker")
    try:
        ticker = args[idx + 1]
    except IndexError as e:
        raise SystemExit("--ticker 뒤에 KRW-DOGE 같은 마켓 코드를 입력하세요.") from e
    return [config.market_by_ticker(ticker)]


def main():
    args = sys.argv[1:]
    markets = _selected_markets(args)

    if "--show" in args:
        for market in markets:
            bm = BudgetManager(market)
            b = bm.load_baseline()
            print(f"\n[{market.TICKER}] {market.BASELINE_FILE}")
            if b is None:
                print("baseline 없음 (봇 첫 실행 시 자동 기록됨)")
            else:
                print(f"baseline 수량: {b['volume']:.8f}")
                print(f"기록 시각:    {b.get('recorded_at')}")
                print(f"메모:        {b.get('note', '-')}")
        return

    if "--zero" in args:
        for market in markets:
            bm = BudgetManager(market)
            bm.save_baseline(0.0, note=f"수동 재설정 (--zero): 모든 {market.TICKER} 수량을 봇이 운용 가능")
            print(f"✅ [{market.TICKER}] baseline = 0 으로 설정.")
        print("⚠ 주의: 다음 사이클에서 기존 보유분이 봇 전략에 따라 매도될 수 있습니다.")
        return

    # 기본: 현재 잔고로 재설정
    import upbit_api as api

    upbit = api.get_upbit_client()
    for market in markets:
        bm = BudgetManager(market)
        coin = api.get_coin_balance(upbit, market.TICKER)
        cur_vol = coin["balance"]
        bm.save_baseline(cur_vol, note=f"수동 재설정: {market.TICKER} 잔고 {cur_vol:.8f} 보호")
        print(f"✅ [{market.TICKER}] baseline = {cur_vol:.8f} 으로 설정 (현재 거래소 잔고).")
    print("   이 수량은 봇이 절대 매도하지 않습니다.")


if __name__ == "__main__":
    main()

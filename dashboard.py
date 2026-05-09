"""
dashboard.py — Streamlit 기반 자동매매 모니터링 대시보드 (regime-aware)

실행:
  streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0

기능:
  - 핵심 지표(KPI) 6개
  - 현재 포지션 카드 (TREND / BB 모드별 자동 분기)
  - 1H 시장 상태 + Regime 표시 + 전략별 매수 조건 체크리스트
  - 누적/일별 손익 차트
  - 거래내역 표 (필터/정렬/CSV 다운로드)
  - 최근 로그 50줄
  - 자동 새로고침
  - 비밀번호 보호
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

import config
import upbit_api as api
import strategy
import mean_revert as mr


# ── 인증 ─────────────────────────────────────────────
def auth_gate() -> bool:
    pw_required = bool(config.DASHBOARD_PASSWORD)
    if not pw_required:
        return True

    if st.session_state.get("auth_ok"):
        return True

    st.title("🔒 Upbit Trader Dashboard")
    pw = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
        if pw == config.DASHBOARD_PASSWORD:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    return False


# ── 데이터 로더 (캐시) ────────────────────────────────
def _read_json(path: str, label: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        st.error(f"{label} 로드 실패: {e}")
        st.stop()
    if not isinstance(data, dict):
        st.error(f"{label} 형식 오류: JSON 객체가 아닙니다.")
        st.stop()
    return data


def _read_json_list(path: str, label: str) -> list:
    """fixed 모드 positions 파일 (list of dict) 로드. 없으면 [] 반환."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        st.error(f"{label} 로드 실패: {e}")
        st.stop()
    if not isinstance(data, list):
        st.error(f"{label} 형식 오류: JSON 배열이 아닙니다.")
        st.stop()
    return data


def _baseline_volume_or_stop(baseline: Optional[dict]) -> float:
    if baseline is None:
        return 0.0
    try:
        return float(baseline["volume"])
    except (KeyError, TypeError, ValueError) as e:
        st.error(f"baseline.json 형식 오류: volume 값을 읽을 수 없습니다. ({e})")
        st.stop()


@st.cache_data(ttl=config.DASHBOARD_CACHE_TTL_SEC)
def load_trades_df() -> pd.DataFrame:
    if not os.path.exists(config.TRADES_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_csv(config.TRADES_FILE, encoding="utf-8-sig")
        if df.empty:
            return df
        df["날짜시간_dt"] = pd.to_datetime(df["날짜시간"], errors="coerce")
        # 손익(원) → 숫자
        if "손익(원)" in df.columns:
            df["손익_숫자"] = (
                df["손익(원)"].astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("+", "", regex=False)
            )
            df["손익_숫자"] = pd.to_numeric(df["손익_숫자"], errors="coerce")
        return df
    except Exception as e:
        st.error(f"trades.csv 로드 실패: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=config.DASHBOARD_CACHE_TTL_SEC)
def load_market_snapshot(ticker: str, candle_count: int):
    """현재가 + 250봉 캔들 + 지표"""
    cur = api.get_current_price(ticker)
    df  = api.get_ohlcv(ticker, "minute60", count=candle_count)
    return cur, df


@st.cache_data(ttl=config.DASHBOARD_CACHE_TTL_SEC)
def load_balances(ticker: str):
    upbit = api.get_upbit_client()
    krw = api.get_krw_balance(upbit)
    coin = api.get_coin_balance(upbit, ticker)
    return krw, coin


def load_log_tail(n: int = 50) -> str:
    if not os.path.exists(config.LOG_FILE):
        return "(로그 없음)"
    try:
        with open(config.LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception as e:
        return f"(로그 읽기 실패: {e})"


# ── 렌더링 ──────────────────────────────────────────
def fmt_won(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f}원"


def render_kpis(market, status: dict, position: Optional[dict], baseline_vol: float,
                exchange_vol: float, krw_balance: float, current_price: float,
                candles: pd.DataFrame):
    s = status or {}
    halt_status = s.get("일일", {}).get("거래중단", False)
    halt_reason = s.get("일일", {}).get("중단사유", "")

    # 봇 운용 자산 평가액
    bot_vol = max(0.0, exchange_vol - baseline_vol)
    cum_pnl = s.get("누적실현손익", 0)
    invested = s.get("누적투자금", 0)
    allocated_cash = max(0.0, market.BUDGET + cum_pnl - invested)
    bot_market_value = bot_vol * current_price + allocated_cash
    today_pnl = s.get("일일", {}).get("실현손익", 0)
    win_rate = s.get("승률", 0)

    pos_label = "보유 중 ✅" if (position and bot_vol > 0) else "무포지션"

    # 현재가 — 직전 1H봉 종가 대비 변화율
    price_delta = None
    if not candles.empty and len(candles) >= 2 and current_price:
        prev_close = float(candles["close"].iloc[-2])
        if prev_close > 0:
            price_delta = f"{(current_price/prev_close - 1)*100:+.2f}%"

    cols = st.columns(7)
    cols[0].metric(
        f"현재가 ({market.TICKER})",
        f"{current_price:,.0f}원" if current_price else "-",
        price_delta,
        help="직전 1H봉 종가 대비 변화율",
    )
    cols[1].metric("배정 예산", f"{market.BUDGET:,.0f}원")
    cols[2].metric(
        "봇 운용 자산",
        f"{bot_market_value:,.0f}원",
        help="KRW 잔고 + 봇이 매수한 BTC 평가액 (사용자 baseline 분 제외)",
    )
    cols[3].metric(
        "누적 손익",
        fmt_won(cum_pnl),
        delta=f"{cum_pnl/market.BUDGET*100:+.2f}%" if market.BUDGET else None,
    )
    cols[4].metric(
        "오늘 손익",
        fmt_won(today_pnl),
        delta=f"{today_pnl/market.BUDGET*100:+.2f}%" if market.BUDGET else None,
    )
    cols[5].metric("승률", f"{win_rate:.1f}%")

    if halt_status:
        cols[6].metric("거래 상태", "⛔ 차단", help=halt_reason, delta_color="inverse")
    else:
        cols[6].metric("거래 상태", "🟢 정상" if pos_label.startswith("보유") else "🟡 대기")


def render_position_card(market, position: dict, current_price: float):
    if not position:
        return
    entry = position["entry_price"]
    pnl_pct = (current_price - entry) / entry * 100 if entry else 0
    rem = position.get("remaining_volume", 0)
    pnl_abs = (current_price - entry) * rem
    stype = position.get("strategy_type", "TREND")
    badge = "🔵 추세 (TREND)" if stype == "TREND" else "🟠 평균회귀 (BB)"

    st.subheader(f"💰 현재 포지션 — {badge}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("매수가", f"{entry:,.0f}원")
    c2.metric("현재가", f"{current_price:,.0f}원", f"{pnl_pct:+.2f}%")
    c3.metric("평가손익", fmt_won(pnl_abs))
    c4.metric("잔량", f"{rem:.8f}")

    sl = position.get("stop_loss_price", 0)

    if stype == "BB":
        # BB 모드: 손절가 / SMA20 목표 / 보유시간
        from datetime import datetime as _dt
        entry_time = position.get("entry_time", "")
        hours_held = 0.0
        try:
            entry_dt = _dt.strptime(entry_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.KST)
            hours_held = (_dt.now(config.KST) - entry_dt).total_seconds() / 3600
        except (ValueError, TypeError):
            pass
        timeout_left = max(0.0, market.BB_MAX_HOLD_BARS - hours_held)
        c1, c2, c3 = st.columns(3)
        c1.metric("손절가", f"{sl:,.0f}원", f"{(sl/entry-1)*100:+.2f}%" if entry else "-")
        c2.metric("목표(SMA20)", "BB 중간선 도달 시 전량 매도",
                  help="현재가가 BB 중간선(SMA20) 이상 되면 평균회귀 익절")
        c3.metric("보유시간", f"{hours_held:.1f}h",
                  f"TIMEOUT까지 {timeout_left:.1f}h",
                  help=f"{market.BB_MAX_HOLD_BARS}h 도달 시 자동 청산")
    else:
        # TREND 모드: 기존 TP1/TP2/트레일링 표시
        high = position.get("highest_price", entry)
        tp1_price = entry * (1 + market.TP1_PCT)
        tp2_price = entry * (1 + market.TP2_PCT)
        trail_trigger = high * (1 - market.TRAILING_STOP_PCT) if position.get("tp1_done") else None

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("손절가", f"{sl:,.0f}원", f"{(sl/entry-1)*100:+.2f}%")
        c2.metric(
            f"TP1 (+{market.TP1_PCT*100:.1f}%)",
            f"{tp1_price:,.0f}원",
            "✓ 완료" if position.get("tp1_done") else "⏳ 대기",
        )
        c3.metric(
            f"TP2 (+{market.TP2_PCT*100:.1f}%)",
            f"{tp2_price:,.0f}원",
            "✓ 완료" if position.get("tp2_done") else "⏳ 대기",
        )
        c4.metric(
            "고점 대비",
            f"{high:,.0f}원",
            f"{(current_price/high-1)*100:+.2f}%" if high else "-",
            help=(f"트레일링 트리거: {trail_trigger:,.0f}원" if trail_trigger else "TP1 이후 트레일링 활성화"),
        )

    entry_time = position.get("entry_time", "")
    st.caption(f"진입 시각: {entry_time}  /  진입 ATR: {position.get('entry_atr', 0):,.0f}")


def render_positions_card_fixed(market, positions: list, current_price: float):
    """Fixed 모드: 다중 포지션을 표 + 합계 메트릭으로 렌더."""
    n = len(positions)
    fixed_pct = market.FIXED_TP_PCT * 100
    st.subheader(f"💰 보유 포지션 (Fixed +{fixed_pct:.1f}% 익절, 다중) — {n}개")

    if n == 0:
        st.info("💤 현재 보유 포지션 없음. 매수 신호 시 자동 진입.")
        return

    # 합계 메트릭
    total_invested = sum(float(p.get("krw_invested", 0)) for p in positions)
    total_volume = sum(float(p.get("remaining_volume", 0)) for p in positions)
    total_market_value = total_volume * current_price if current_price else 0
    unrealized = total_market_value - total_invested
    unrealized_pct = (unrealized / total_invested * 100) if total_invested else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("보유 포지션", f"{n}개")
    c2.metric("투자 원금 합계", f"{total_invested:,.0f}원")
    c3.metric("평가금액 (현재가)", f"{total_market_value:,.0f}원")
    c4.metric("평가손익", fmt_won(unrealized), f"{unrealized_pct:+.2f}%")

    # 포지션 표
    rows = []
    for p in positions:
        entry = float(p.get("entry_price", 0))
        target = float(p.get("target_price", entry * (1 + market.FIXED_TP_PCT)))
        rem_vol = float(p.get("remaining_volume", 0))
        invested = float(p.get("krw_invested", 0))
        cur_value = rem_vol * current_price if current_price else 0
        pnl_pct = (current_price / entry - 1) * 100 if entry and current_price else 0
        gap_to_target = (target / current_price - 1) * 100 if current_price else 0
        rows.append({
            "진입시각":    p.get("entry_time", "-"),
            "매수가":      f"{entry:,.2f}",
            "수량":        f"{rem_vol:.8f}",
            "투자원금":    f"{invested:,.0f}",
            "현재 평가":   f"{cur_value:,.0f}",
            "현재 손익률": f"{pnl_pct:+.2f}%",
            "목표가":      f"{target:,.2f}",
            "목표까지":    f"{gap_to_target:+.2f}%",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_market_state(market, df: pd.DataFrame, current_price: float):
    st.subheader("📈 1H 시장 상태 / Regime / 매수 조건")
    if df.empty or len(df) < market.MA_TREND_LONG + 5:
        st.info("지표 계산을 위한 데이터 부족")
        return

    ind = strategy.calc_indicators(df, market)
    cur = ind.iloc[-1]
    ma20, ma50, ma200 = float(cur["ma20"]), float(cur["ma50"]), float(cur["ma200"])
    rsi, atr = float(cur["rsi"]), float(cur["atr"])

    # ── Regime 판정 ──
    regime_info = strategy.detect_regime(df, market)
    regime = regime_info["regime"]
    metrics = regime_info.get("metrics", {})
    regime_badge = {
        "TREND":    "🔵 추세장 (TREND) — 추세 눌림목 전략 활성",
        "SIDEWAYS": "🟠 횡보장 (SIDEWAYS) — BB 평균회귀 전략 활성",
        "BEAR":     "🔴 약세장 (BEAR) — 신규 매수 차단",
            "NEUTRAL":  "⚪ 데이터 부족",
    }.get(regime, regime)
    st.markdown(f"**현재 Regime: {regime_badge}**")
    if metrics:
        st.caption(
            f"MA200 {market.REGIME_LOOKBACK_BARS}봉 기울기 {metrics.get('ma200_slope', 0)*100:+.2f}% / "
            f"P/MA200 {metrics.get('price_to_ma200', 0)*100:+.2f}%"
        )

    # ── 추세 지표 + BB 지표 (한 줄) ──
    cols = st.columns(5)
    cols[0].metric("MA20",    f"{ma20:,.0f}",    f"{(current_price/ma20-1)*100:+.2f}%")
    cols[1].metric("MA50",    f"{ma50:,.0f}",    f"{(current_price/ma50-1)*100:+.2f}%")
    cols[2].metric("MA200",   f"{ma200:,.0f}",   f"{(current_price/ma200-1)*100:+.2f}%")
    cols[3].metric("RSI(14)", f"{rsi:.1f}")
    cols[4].metric("ATR(14)", f"{atr:,.0f}")

    # BB 지표
    bb = mr.calc_bb(df, market)
    bb_lower = float(bb.iloc[-1]["bb_lower"])
    bb_mid   = float(bb.iloc[-1]["bb_mid"])
    bb_upper = float(bb.iloc[-1]["bb_upper"])
    bcols = st.columns(3)
    bcols[0].metric(f"BB하단 ({market.BB_PERIOD},{market.BB_STD}σ)",
                    f"{bb_lower:,.0f}", f"{(current_price/bb_lower-1)*100:+.2f}%")
    bcols[1].metric("BB중간 (SMA20)",
                    f"{bb_mid:,.0f}",   f"{(current_price/bb_mid-1)*100:+.2f}%")
    bcols[2].metric("BB상단",
                    f"{bb_upper:,.0f}", f"{(current_price/bb_upper-1)*100:+.2f}%")

    # ── Regime 별 매수 조건 체크리스트 ──
    if regime == "TREND":
        range_pos = None
        if market.ENTRY_RANGE_LOOKBACK_BARS > 0:
            recent = df.tail(market.ENTRY_RANGE_LOOKBACK_BARS)
            recent_low = float(recent["low"].min())
            recent_high = float(recent["high"].max())
            if recent_high > recent_low:
                range_pos = (current_price - recent_low) / (recent_high - recent_low)
        checks = {
            "추세 (P > MA200)":                                          current_price > ma200,
            "정렬 (MA50 > MA200)":                                        ma50 > ma200,
            f"P ≥ MA50·{1-market.ENTRY_MID_MA_BUFFER_PCT:.3f}":            current_price >= ma50 * (1 - market.ENTRY_MID_MA_BUFFER_PCT),
            f"눌림목 (P ≤ MA20·{1+market.ENTRY_PULLBACK_TOLERANCE:.3f})":  current_price <= ma20 * (1 + market.ENTRY_PULLBACK_TOLERANCE),
            f"RSI ∈ [{market.RSI_BUY_MIN},{market.ENTRY_RSI_MAX}]":        market.RSI_BUY_MIN <= rsi <= market.ENTRY_RSI_MAX,
        }
        # 직전 완성봉이 TREND_BREAK 조건을 만족하면 매수 보류 (즉시 청산 방지)
        confirm_bars = max(1, market.TREND_BREAK_CONFIRM_BARS)
        ma50_series = df["close"].rolling(window=market.MA_TREND_MID).mean()
        no_break = True
        if len(df) >= market.MA_TREND_MID + confirm_bars + 1:
            closed_closes = df["close"].iloc[:-1].tail(confirm_bars)
            closed_ma50 = ma50_series.iloc[:-1].tail(confirm_bars)
            if len(closed_closes) == confirm_bars and not closed_ma50.isna().any():
                threshold_series = closed_ma50 * (1 - market.TREND_BREAK_BUFFER_PCT)
                no_break = not bool((closed_closes < threshold_series).all())
        checks[f"직전{confirm_bars}봉 종가 ≥ MA50·{1-market.TREND_BREAK_BUFFER_PCT:.3f}"] = no_break
        if range_pos is not None:
            checks[f"최근{market.ENTRY_RANGE_LOOKBACK_BARS}봉 상단 회피 ({range_pos*100:.0f}% ≤ {market.ENTRY_RANGE_MAX_POSITION*100:.0f}%)"] = (
                range_pos <= market.ENTRY_RANGE_MAX_POSITION
            )
        passed = sum(checks.values())
        st.write(f"**🔵 TREND 매수 조건: {passed}/{len(checks)}**")
        cc = st.columns(len(checks))
        for i, (label, ok) in enumerate(checks.items()):
            cc[i].markdown(f"{'✅' if ok else '⬜'} {label}")

    elif regime == "SIDEWAYS":
        cond_bb_touch = (
            float(cur["low"]) <= bb_lower * (1 + market.BB_TOL)
            and current_price <= bb_mid
        )
        checks = {
            f"BB 하단 터치 (L ≤ 하단·{1+market.BB_TOL:.3f}, P ≤ 중간선)": cond_bb_touch,
            "양봉 반등 (close > open)":                    float(cur["close"]) > float(cur["open"]),
            f"RSI < {market.BB_RSI_MAX:.0f}":               rsi < market.BB_RSI_MAX,
            f"P > MA200·{market.BB_MA200_FLOOR}":           current_price > ma200 * market.BB_MA200_FLOOR,
        }
        passed = sum(checks.values())
        st.write(f"**🟠 BB 평균회귀 매수 조건: {passed}/4**")
        cc = st.columns(4)
        for i, (label, ok) in enumerate(checks.items()):
            cc[i].markdown(f"{'✅' if ok else '⬜'} {label}")

    else:  # BEAR / NEUTRAL
        st.warning(f"⛔ {regime} 상태 — 신규 매수 평가하지 않음 (자본 보존)")


def render_charts(trades_df: pd.DataFrame):
    st.subheader("📊 손익 차트")
    if trades_df.empty:
        st.info("거래 내역이 없습니다.")
        return

    sells = trades_df[trades_df["종류"] == "매도"].copy()
    if sells.empty:
        st.info("매도(실현) 내역이 없습니다.")
        return

    sells = sells.sort_values("날짜시간_dt").dropna(subset=["손익_숫자"])
    sells["누적손익"] = sells["손익_숫자"].cumsum()

    # 누적 손익
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(
        x=sells["날짜시간_dt"], y=sells["누적손익"],
        mode="lines+markers", name="누적 실현손익",
        line=dict(width=2),
    ))
    fig_cum.update_layout(
        height=320, margin=dict(l=10, r=10, t=30, b=10),
        title="누적 실현손익 추이",
        xaxis_title=None, yaxis_title="원",
    )
    st.plotly_chart(fig_cum, use_container_width=True)

    # 일별 손익 (최근 30일)
    sells["날짜"] = sells["날짜시간_dt"].dt.date
    end = datetime.now(config.KST).date()
    start = end - timedelta(days=29)
    daily = sells.groupby("날짜")["손익_숫자"].sum().reindex(
        [start + timedelta(days=i) for i in range(30)], fill_value=0
    )
    colors = ["#ef4444" if v < 0 else "#10b981" for v in daily.values]
    fig_day = go.Figure(go.Bar(x=daily.index, y=daily.values, marker_color=colors))
    fig_day.update_layout(
        height=280, margin=dict(l=10, r=10, t=30, b=10),
        title=f"일별 실현손익 (최근 30일, 합계 {daily.sum():+,.0f}원)",
        xaxis_title=None, yaxis_title="원",
    )
    st.plotly_chart(fig_day, use_container_width=True)


def render_trade_table(trades_df: pd.DataFrame, key_prefix: str):
    st.subheader("📋 거래 내역")
    if trades_df.empty:
        st.info("거래 내역이 없습니다.")
        return

    # 필터
    col1, col2 = st.columns([1, 2])
    types = col1.multiselect(
        "종류",
        options=["매수", "매도"],
        default=["매수", "매도"],
        key=f"{key_prefix}_trade_types",
    )
    n_rows = col2.slider("표시 행 수", 10, 500, 50, key=f"{key_prefix}_trade_rows")

    f = trades_df.copy()
    f = f[f["종류"].isin(types)]
    f = f.sort_values("날짜시간_dt", ascending=False).head(n_rows)

    show_cols = [
        "날짜시간", "종류", "사유",
        "매수가(원)", "매도가(원)", "수량",
        "매수금액(원)", "매도금액(원)",
        "손익(원)", "손익률(%)",
        "MA20", "MA50", "MA200", "RSI", "ATR",
    ]
    show_cols = [c for c in show_cols if c in f.columns]
    st.dataframe(f[show_cols], use_container_width=True, hide_index=True)

    # CSV 다운로드
    csv = trades_df.drop(columns=["날짜시간_dt", "손익_숫자"], errors="ignore").to_csv(
        index=False, encoding="utf-8-sig"
    )
    st.download_button(
        "📥 전체 CSV 다운로드",
        data=csv,
        file_name=f"{key_prefix}_trades.csv",
        mime="text/csv",
        key=f"{key_prefix}_trade_csv",
    )


def render_log_tail():
    with st.expander("📜 최근 로그 (마지막 50줄)", expanded=False):
        st.code(load_log_tail(50), language="log")


# ── 메인 ────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Upbit Trader",
        page_icon="🤖",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] { font-size: 1.6rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if not auth_gate():
        return

    st_autorefresh(interval=config.DASHBOARD_REFRESH_SEC * 1000, key="auto_refresh")

    # 헤더
    cols = st.columns([4, 1])
    cols[0].title("🤖 업비트 자동매매 대시보드")
    cols[1].caption(f"마지막 갱신: {datetime.now(config.KST).strftime('%Y-%m-%d %H:%M:%S')} (KST)")

    trades_df = load_trades_df()
    markets = config.active_markets()
    tabs = st.tabs([f"{m.name} · {m.TICKER}" for m in markets])

    for tab, market in zip(tabs, markets):
        with tab:
            status   = _read_json(market.STATUS_FILE, market.STATUS_FILE) or {}
            baseline = _read_json(market.BASELINE_FILE, market.BASELINE_FILE)
            baseline_vol = _baseline_volume_or_stop(baseline)
            is_fixed_mode = (market.EXIT_STRATEGY == "fixed")
            if is_fixed_mode:
                positions_list = _read_json_list(market.POSITIONS_FILE, market.POSITIONS_FILE)
                position = positions_list[0] if positions_list else None  # KPI에서 "보유 중" 표시용
            else:
                positions_list = []
                position = _read_json(market.POSITION_FILE, market.POSITION_FILE)

            if "티커" in trades_df.columns:
                market_trades = trades_df[trades_df["티커"] == market.TICKER].copy()
            else:
                market_trades = trades_df.copy()

            try:
                current_price, candles = load_market_snapshot(market.TICKER, market.CANDLE_COUNT)
            except Exception as e:
                st.error(f"시세 조회 실패: {e}")
                current_price, candles = 0.0, pd.DataFrame()

            try:
                krw_balance, coin_info = load_balances(market.TICKER)
                exchange_vol = coin_info["balance"]
            except Exception as e:
                st.warning(f"잔고 조회 실패 (API 키 없음 또는 권한 부족): {e}")
                krw_balance, exchange_vol = 0.0, 0.0

            render_kpis(market, status, position, baseline_vol, exchange_vol, krw_balance, current_price, candles)
            st.divider()

            if is_fixed_mode:
                render_positions_card_fixed(market, positions_list, current_price)
                st.divider()
            elif position and (exchange_vol - baseline_vol) > 0:
                render_position_card(market, position, current_price)
                st.divider()
            else:
                coin_symbol = market.TICKER.split("-")[-1]
                st.info(f"💤 현재 봇 보유 포지션 없음. (사용자 보유 baseline: {baseline_vol:.8f} {coin_symbol})")
                st.divider()

            render_market_state(market, candles, current_price)
            st.divider()

            render_charts(market_trades)
            st.divider()

            render_trade_table(market_trades, key_prefix=market.TICKER.replace("-", "_"))

            mode_desc = (
                f"🟣 Fixed +{market.FIXED_TP_PCT*100:.1f}% 익절 (다중포지션, 손절·트레일링 없음)"
                if is_fixed_mode
                else "🔵 추세 눌림목 + 🟠 BB 평균회귀 (Regime 자동 선택, TP1/TP2/트레일링/손절)"
            )
            st.caption(
                f"Ticker: {market.TICKER}  •  Budget: {market.BUDGET:,.0f}원  •  "
                f"Position size: {market.POSITION_PCT*100:.0f}%  •  "
                f"매도 모드: {mode_desc}"
            )

    render_log_tail()


if __name__ == "__main__":
    main()

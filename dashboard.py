"""FastAPI backend for the lightweight HTML dashboard.

Run locally:
  uvicorn dashboard:app --host 127.0.0.1 --port 8501

Nginx is the public entry point in production. The API process only reads trading
state and calls Upbit read endpoints; it never places or cancels orders.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import math
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import mean_revert as mr
import strategy
import upbit_api as api


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
BRAND_DIR = BASE_DIR / "brand-assets"
SESSION_COOKIE = "upbit_dashboard_session"
SESSION_MAX_AGE_SEC = 12 * 60 * 60

app = FastAPI(
    title="Upbit Trader Dashboard",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class LoginRequest(BaseModel):
    password: str


_snapshot_lock = threading.Lock()
_snapshot_data: dict[str, Any] | None = None
_snapshot_expires_at = 0.0


def _data_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else BASE_DIR / candidate


def _read_json_dict(path: str) -> dict[str, Any]:
    target = _data_path(path)
    if not target.exists():
        return {}
    with target.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON 객체가 아닙니다.")
    return value


def _read_json_list(path: str) -> list[dict[str, Any]]:
    target = _data_path(path)
    if not target.exists():
        return []
    with target.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path}: JSON 객체 배열이 아닙니다.")
    return value


def _load_trades() -> pd.DataFrame:
    target = _data_path(config.TRADES_FILE)
    if not target.exists():
        return pd.DataFrame()
    frame = pd.read_csv(target, encoding="utf-8-sig")
    if frame.empty:
        return frame
    if "날짜시간" in frame.columns:
        frame["날짜시간_dt"] = pd.to_datetime(frame["날짜시간"], errors="coerce")
    if "손익(원)" in frame.columns:
        frame["손익_숫자"] = pd.to_numeric(
            frame["손익(원)"].astype(str).str.replace(",", "", regex=False).str.replace("+", "", regex=False),
            errors="coerce",
        )
    return frame


def _load_log_tail(line_count: int = 50) -> str:
    target = _data_path(config.LOG_FILE)
    if not target.exists():
        return "(로그 없음)"
    try:
        with target.open("r", encoding="utf-8") as handle:
            return "".join(handle.readlines()[-line_count:])
    except Exception as exc:
        return f"(로그 읽기 실패: {exc})"


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _load_balances() -> tuple[float, dict[str, float], str | None]:
    if not config.UPBIT_ACCESS_KEY or not config.UPBIT_SECRET_KEY:
        return 0.0, {}, "API 키가 없어 잔고를 조회하지 못했습니다."
    try:
        balances = api.get_upbit_client().get_balances()
        if not isinstance(balances, list):
            raise ValueError("예상하지 못한 잔고 응답 형식")
        krw = 0.0
        coins: dict[str, float] = {}
        for item in balances:
            currency = str(item.get("currency", ""))
            balance = _finite_float(item.get("balance"))
            if currency == "KRW":
                krw = balance
            elif currency:
                coins[f"KRW-{currency}"] = balance
        return krw, coins, None
    except Exception as exc:
        return 0.0, {}, f"잔고 조회 실패: {exc}"


def _build_kpis(
    market: config.MarketSettings,
    status: dict[str, Any],
    position: dict[str, Any] | None,
    baseline_volume: float,
    exchange_volume: float,
    krw_balance: float,
    current_price: float,
    candles: pd.DataFrame,
) -> dict[str, Any]:
    daily = status.get("일일", {}) if isinstance(status.get("일일", {}), dict) else {}
    cumulative_pnl = _finite_float(status.get("누적실현손익"))
    invested = _finite_float(status.get("누적투자금"))
    bot_volume = max(0.0, exchange_volume - baseline_volume)
    allocated_cash = max(0.0, market.BUDGET + cumulative_pnl - invested)
    today_pnl = _finite_float(daily.get("실현손익"))
    price_delta_pct = None
    if len(candles) >= 2 and current_price:
        previous_close = _finite_float(candles["close"].iloc[-2])
        if previous_close > 0:
            price_delta_pct = (current_price / previous_close - 1) * 100
    return {
        "current_price": current_price,
        "price_delta_pct": price_delta_pct,
        "budget": market.BUDGET,
        "bot_market_value": bot_volume * current_price + allocated_cash,
        "cumulative_pnl": cumulative_pnl,
        "cumulative_pnl_pct": cumulative_pnl / market.BUDGET * 100 if market.BUDGET else None,
        "today_pnl": today_pnl,
        "today_pnl_pct": today_pnl / market.BUDGET * 100 if market.BUDGET else None,
        "win_rate": _finite_float(status.get("승률")),
        "halted": bool(daily.get("거래중단", False)),
        "halt_reason": str(daily.get("중단사유", "")),
        "position_held": bool(position and bot_volume > 0),
        "krw_balance": krw_balance,
    }


def _build_position(
    market: config.MarketSettings,
    positions: list[dict[str, Any]],
    position: dict[str, Any] | None,
    status: dict[str, Any],
    current_price: float,
    baseline_volume: float,
    exchange_volume: float,
) -> dict[str, Any]:
    if market.EXIT_STRATEGY == "fixed":
        rows = []
        total_invested = 0.0
        total_volume = 0.0
        total_entry_cost = 0.0
        for item in positions:
            entry = _finite_float(item.get("entry_price"))
            volume = _finite_float(item.get("remaining_volume"))
            invested = _finite_float(item.get("krw_invested"))
            total_invested += invested
            total_volume += volume
            total_entry_cost += entry * volume
            rows.append({
                "entry_time": str(item.get("entry_time", "-")),
                "entry_price": entry,
                "volume": volume,
                "invested": invested,
                "market_value": volume * current_price,
                "pnl_pct": (current_price / entry - 1) * 100 if entry and current_price else 0.0,
            })
        average_entry = total_entry_cost / total_volume if total_volume else 0.0
        market_value = total_volume * current_price
        unrealized = market_value - total_invested
        sell_count = int(status.get("평단분할매도횟수", 0) or 0)
        last_sell_at = None
        cooldown_remaining_hours = 0.0
        try:
            raw_last_sell = str(status.get("마지막평단매도시각", ""))
            if raw_last_sell:
                parsed = datetime.fromisoformat(raw_last_sell)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=config.KST)
                last_sell_at = parsed.astimezone(config.KST)
                cooldown_until = last_sell_at + timedelta(hours=config.AVERAGE_EXIT_COOLDOWN_HOURS)
                cooldown_remaining_hours = max(
                    0.0, (cooldown_until - datetime.now(config.KST)).total_seconds() / 3600
                )
        except (TypeError, ValueError):
            pass
        return {
            "mode": "fixed",
            "count": len(rows),
            "average_entry": average_entry,
            "current_price": current_price,
            "total_volume": total_volume,
            "total_invested": total_invested,
            "market_value": market_value,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": unrealized / total_invested * 100 if total_invested else 0.0,
            "sequence_sell_count": sell_count,
            "last_sell_at": last_sell_at.strftime("%Y-%m-%d %H:%M") if last_sell_at else "-",
            "cooldown_remaining_hours": cooldown_remaining_hours,
            "next_rule": (
                "+3% 도달 시 30%"
                if sell_count == 0
                else "+9% 전량 / +6% 60% / +3% 30%"
            ),
            "rows": rows,
        }

    if not position or max(0.0, exchange_volume - baseline_volume) <= 0:
        return {"mode": "trailing", "count": 0, "baseline_volume": baseline_volume}

    entry = _finite_float(position.get("entry_price"))
    remaining = _finite_float(position.get("remaining_volume"))
    strategy_type = str(position.get("strategy_type", "TREND"))
    result: dict[str, Any] = {
        "mode": "trailing",
        "count": 1,
        "strategy_type": strategy_type,
        "entry_price": entry,
        "current_price": current_price,
        "pnl_pct": (current_price - entry) / entry * 100 if entry else 0.0,
        "unrealized_pnl": (current_price - entry) * remaining,
        "remaining_volume": remaining,
        "stop_loss_price": _finite_float(position.get("stop_loss_price")),
        "entry_time": str(position.get("entry_time", "")),
        "entry_atr": _finite_float(position.get("entry_atr")),
    }
    if strategy_type == "BB":
        hours_held = 0.0
        try:
            entry_time = datetime.strptime(result["entry_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.KST)
            hours_held = max(0.0, (datetime.now(config.KST) - entry_time).total_seconds() / 3600)
        except (TypeError, ValueError):
            pass
        result.update({
            "hours_held": hours_held,
            "timeout_left_hours": max(0.0, market.BB_MAX_HOLD_BARS - hours_held),
            "max_hold_hours": market.BB_MAX_HOLD_BARS,
        })
    else:
        highest = _finite_float(position.get("highest_price"), entry)
        tp1_done = bool(position.get("tp1_done"))
        result.update({
            "highest_price": highest,
            "high_delta_pct": (current_price / highest - 1) * 100 if highest else 0.0,
            "tp1_price": entry * (1 + market.TP1_PCT),
            "tp1_pct": market.TP1_PCT * 100,
            "tp1_done": tp1_done,
            "tp2_price": entry * (1 + market.TP2_PCT),
            "tp2_pct": market.TP2_PCT * 100,
            "tp2_done": bool(position.get("tp2_done")),
            "trailing_trigger": highest * (1 - market.TRAILING_STOP_PCT) if tp1_done else None,
        })
    return result


def _build_market_state(
    market: config.MarketSettings,
    candles: pd.DataFrame,
    current_price: float,
) -> dict[str, Any]:
    if candles.empty or len(candles) < market.MA_TREND_LONG + 5:
        return {"available": False, "message": "지표 계산을 위한 데이터가 부족합니다."}

    indicators = strategy.calc_indicators(candles, market)
    current = indicators.iloc[-1]
    ma20 = _finite_float(current.get("ma20"))
    ma50 = _finite_float(current.get("ma50"))
    ma200 = _finite_float(current.get("ma200"))
    rsi = _finite_float(current.get("rsi"))
    atr = _finite_float(current.get("atr"))
    bands = mr.calc_bb(candles, market).iloc[-1]
    bb_lower = _finite_float(bands.get("bb_lower"))
    bb_mid = _finite_float(bands.get("bb_mid"))
    bb_upper = _finite_float(bands.get("bb_upper"))
    regime_info = strategy.detect_regime(candles, market)
    regime = str(regime_info.get("regime", "NEUTRAL"))
    checks: list[dict[str, Any]] = []

    if regime == "TREND":
        raw_checks: list[tuple[str, bool]] = [
            ("추세 (P > MA200)", current_price > ma200),
            ("정렬 (MA50 > MA200)", ma50 > ma200),
            (f"P ≥ MA50·{1-market.ENTRY_MID_MA_BUFFER_PCT:.3f}", current_price >= ma50 * (1 - market.ENTRY_MID_MA_BUFFER_PCT)),
            (f"눌림목 (P ≤ MA20·{1+market.ENTRY_PULLBACK_TOLERANCE:.3f})", current_price <= ma20 * (1 + market.ENTRY_PULLBACK_TOLERANCE)),
            (f"RSI ∈ [{market.RSI_BUY_MIN},{market.ENTRY_RSI_MAX}]", market.RSI_BUY_MIN <= rsi <= market.ENTRY_RSI_MAX),
        ]
        confirm_bars = max(1, market.TREND_BREAK_CONFIRM_BARS)
        ma50_series = candles["close"].rolling(window=market.MA_TREND_MID).mean()
        no_break = True
        if len(candles) >= market.MA_TREND_MID + confirm_bars + 1:
            closes = candles["close"].iloc[:-1].tail(confirm_bars)
            closed_ma50 = ma50_series.iloc[:-1].tail(confirm_bars)
            if len(closes) == confirm_bars and not closed_ma50.isna().any():
                no_break = not bool((closes < closed_ma50 * (1 - market.TREND_BREAK_BUFFER_PCT)).all())
        raw_checks.append((f"직전{confirm_bars}봉 종가 ≥ MA50·{1-market.TREND_BREAK_BUFFER_PCT:.3f}", no_break))
        if market.ENTRY_RANGE_LOOKBACK_BARS > 0:
            recent = candles.tail(market.ENTRY_RANGE_LOOKBACK_BARS)
            low, high = _finite_float(recent["low"].min()), _finite_float(recent["high"].max())
            if high > low:
                range_position = (current_price - low) / (high - low)
                raw_checks.append((
                    f"최근{market.ENTRY_RANGE_LOOKBACK_BARS}봉 상단 회피 ({range_position*100:.0f}% ≤ {market.ENTRY_RANGE_MAX_POSITION*100:.0f}%)",
                    range_position <= market.ENTRY_RANGE_MAX_POSITION,
                ))
        checks = [{"label": label, "passed": passed} for label, passed in raw_checks]
    elif regime == "SIDEWAYS":
        raw_checks = [
            (f"BB 하단 터치 (L ≤ 하단·{1+market.BB_TOL:.3f}, P ≤ 중간선)", _finite_float(current.get("low")) <= bb_lower * (1 + market.BB_TOL) and current_price <= bb_mid),
            ("양봉 반등 (close > open)", _finite_float(current.get("close")) > _finite_float(current.get("open"))),
            (f"RSI < {market.BB_RSI_MAX:.0f}", rsi < market.BB_RSI_MAX),
            (f"P > MA200·{market.BB_MA200_FLOOR}", current_price > ma200 * market.BB_MA200_FLOOR),
        ]
        checks = [{"label": label, "passed": passed} for label, passed in raw_checks]

    metrics = regime_info.get("metrics", {})
    return {
        "available": True,
        "regime": regime,
        "regime_reason": str(regime_info.get("reason", "")),
        "regime_metrics": {
            "ma200_slope_pct": _finite_float(metrics.get("ma200_slope")) * 100,
            "price_to_ma200_pct": _finite_float(metrics.get("price_to_ma200")) * 100,
        },
        "indicators": {"ma20": ma20, "ma50": ma50, "ma200": ma200, "rsi": rsi, "atr": atr},
        "bands": {"lower": bb_lower, "mid": bb_mid, "upper": bb_upper, "period": market.BB_PERIOD, "std": market.BB_STD},
        "checks": checks,
        "checks_passed": sum(bool(item["passed"]) for item in checks),
    }


def _build_charts(trades: pd.DataFrame) -> dict[str, Any]:
    empty = {"cumulative": [], "daily": [], "daily_total": 0.0}
    if trades.empty or "종류" not in trades.columns or "손익_숫자" not in trades.columns:
        return empty
    sells = trades[trades["종류"] == "매도"].copy()
    if sells.empty or "날짜시간_dt" not in sells.columns:
        return empty
    sells = sells.sort_values("날짜시간_dt").dropna(subset=["날짜시간_dt", "손익_숫자"])
    sells["누적손익"] = sells["손익_숫자"].cumsum()
    cumulative = [
        {"time": row["날짜시간_dt"].isoformat(), "value": _finite_float(row["누적손익"])}
        for _, row in sells.iterrows()
    ]
    today = datetime.now(config.KST).date()
    start = today - timedelta(days=29)
    sells["날짜"] = sells["날짜시간_dt"].dt.date
    daily_series = sells.groupby("날짜")["손익_숫자"].sum().reindex(
        [start + timedelta(days=index) for index in range(30)], fill_value=0
    )
    daily = [{"date": day.isoformat(), "value": _finite_float(value)} for day, value in daily_series.items()]
    return {"cumulative": cumulative, "daily": daily, "daily_total": _finite_float(daily_series.sum())}


def _trade_records(trades: pd.DataFrame, limit: int = 500) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    frame = trades.sort_values("날짜시간_dt", ascending=False) if "날짜시간_dt" in trades.columns else trades.iloc[::-1]
    hidden = {"날짜시간_dt", "손익_숫자"}
    columns = [column for column in frame.columns if column not in hidden]
    return [
        {column: _json_value(row[column]) for column in columns}
        for _, row in frame.head(limit).iterrows()
    ]


def _market_trades(all_trades: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if all_trades.empty or "티커" not in all_trades.columns:
        return all_trades.copy()
    return all_trades[all_trades["티커"] == ticker].copy()


def _build_dashboard_snapshot() -> dict[str, Any]:
    warnings: list[str] = []
    try:
        trades = _load_trades()
    except Exception as exc:
        trades = pd.DataFrame()
        warnings.append(f"거래 내역 로드 실패: {exc}")

    krw_balance, coin_balances, balance_warning = _load_balances()
    if balance_warning:
        warnings.append(balance_warning)

    markets_payload = []
    for market in config.active_markets():
        market_warnings: list[str] = []
        try:
            status = _read_json_dict(market.STATUS_FILE)
            baseline = _read_json_dict(market.BASELINE_FILE)
            baseline_volume = _finite_float(baseline.get("volume"))
            if market.EXIT_STRATEGY == "fixed":
                positions = _read_json_list(market.POSITIONS_FILE)
                position = positions[0] if positions else None
            else:
                positions = []
                position = _read_json_dict(market.POSITION_FILE) or None
        except Exception as exc:
            status, baseline_volume, positions, position = {}, 0.0, [], None
            market_warnings.append(f"상태 파일 로드 실패: {exc}")

        try:
            current_price = api.get_current_price(market.TICKER)
            candles = api.get_ohlcv(market.TICKER, "minute60", count=market.CANDLE_COUNT)
            if not current_price:
                market_warnings.append("현재가 조회에 실패했습니다.")
            if candles.empty:
                market_warnings.append("캔들 조회에 실패했습니다.")
        except Exception as exc:
            current_price, candles = 0.0, pd.DataFrame()
            market_warnings.append(f"시세 조회 실패: {exc}")

        exchange_volume = coin_balances.get(market.TICKER, 0.0)
        scoped_trades = _market_trades(trades, market.TICKER)
        markets_payload.append({
            "name": market.name,
            "ticker": market.TICKER,
            "warnings": market_warnings,
            "kpis": _build_kpis(market, status, position, baseline_volume, exchange_volume, krw_balance, current_price, candles),
            "position": _build_position(
                market, positions, position, status, current_price, baseline_volume, exchange_volume
            ),
            "market_state": _build_market_state(market, candles, current_price),
            "charts": _build_charts(scoped_trades),
            "trades": _trade_records(scoped_trades),
            "settings": {
                "budget": market.BUDGET,
                "position_pct": market.POSITION_PCT * 100,
                "exit_strategy": market.EXIT_STRATEGY,
                "average_exit_cooldown_hours": config.AVERAGE_EXIT_COOLDOWN_HOURS,
            },
        })

    return {
        "generated_at": datetime.now(config.KST).isoformat(),
        "refresh_sec": config.DASHBOARD_REFRESH_SEC,
        "cache_ttl_sec": config.DASHBOARD_CACHE_TTL_SEC,
        "warnings": warnings,
        "markets": markets_payload,
        "log": _load_log_tail(50),
    }


def _dashboard_snapshot(force: bool = False) -> dict[str, Any]:
    global _snapshot_data, _snapshot_expires_at
    now = time.monotonic()
    if not force and _snapshot_data is not None and now < _snapshot_expires_at:
        return _snapshot_data
    with _snapshot_lock:
        now = time.monotonic()
        if not force and _snapshot_data is not None and now < _snapshot_expires_at:
            return _snapshot_data
        _snapshot_data = _build_dashboard_snapshot()
        _snapshot_expires_at = now + max(1, config.DASHBOARD_CACHE_TTL_SEC)
        return _snapshot_data


def _session_key() -> bytes:
    return hashlib.sha256((config.DASHBOARD_PASSWORD + "|upbit-dashboard").encode("utf-8")).digest()


def _create_session_token() -> str:
    expires_at = int(time.time()) + SESSION_MAX_AGE_SEC
    payload = f"{expires_at}.{secrets.token_urlsafe(16)}"
    signature = hmac.new(_session_key(), payload.encode("utf-8"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded_signature}"


def _valid_session_token(token: str | None) -> bool:
    if not config.DASHBOARD_PASSWORD:
        return True
    if not token:
        return False
    try:
        expires_at, nonce, signature = token.split(".", 2)
        if int(expires_at) < int(time.time()):
            return False
        payload = f"{expires_at}.{nonce}"
        expected = base64.urlsafe_b64encode(
            hmac.new(_session_key(), payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        return hmac.compare_digest(signature, expected)
    except (TypeError, ValueError):
        return False


def _is_authenticated(request: Request) -> bool:
    return _valid_session_token(request.cookies.get(SESSION_COOKIE))


def _require_auth(request: Request) -> None:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


@app.middleware("http")
async def private_api_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/session")
def session_status(request: Request) -> dict[str, bool]:
    return {
        "authenticated": _is_authenticated(request),
        "password_required": bool(config.DASHBOARD_PASSWORD),
    }


@app.post("/api/login")
def login(payload: LoginRequest, request: Request) -> JSONResponse:
    if config.DASHBOARD_PASSWORD and not hmac.compare_digest(payload.password, config.DASHBOARD_PASSWORD):
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        SESSION_COOKIE,
        _create_session_token(),
        max_age=SESSION_MAX_AGE_SEC,
        httponly=True,
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/logout")
def logout(_: None = Depends(_require_auth)) -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/dashboard")
def dashboard_snapshot(refresh: bool = False, _: None = Depends(_require_auth)) -> dict[str, Any]:
    return _dashboard_snapshot(force=refresh)


@app.get("/api/trades/{ticker}/csv")
def download_trades(ticker: str, _: None = Depends(_require_auth)) -> Response:
    try:
        config.market_by_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    trades = _market_trades(_load_trades(), ticker)
    hidden = [column for column in ("날짜시간_dt", "손익_숫자") if column in trades.columns]
    csv_text = trades.drop(columns=hidden).to_csv(index=False, encoding="utf-8-sig")
    payload = io.BytesIO(csv_text.encode("utf-8-sig"))
    filename = f"{ticker.replace('-', '_')}_trades.csv"
    return StreamingResponse(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if BRAND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=BRAND_DIR), name="assets")
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

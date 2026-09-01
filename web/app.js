"use strict";

const state = {
  data: null,
  activeTicker: null,
  refreshTimer: null,
  tradeFilters: {},
  logOpen: false,
};

const $ = (selector) => document.querySelector(selector);
const views = {
  login: $("#login-view"),
  loading: $("#loading-view"),
  app: $("#app-view"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showView(name) {
  Object.entries(views).forEach(([key, element]) => {
    element.hidden = key !== name;
  });
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) {
    showView("login");
    throw new Error("로그인이 필요합니다.");
  }
  if (!response.ok) {
    let message = `요청 실패 (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (_) {
      // Use the status message when the body is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

function number(value, maximumFractionDigits = 0) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits }).format(Number(value));
}

function won(value, signed = false) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  const numeric = Number(value);
  const sign = signed && numeric > 0 ? "+" : "";
  return `${sign}${number(numeric)}원`;
}

function percent(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  const numeric = Number(value);
  return `${numeric > 0 ? "+" : ""}${numeric.toFixed(digits)}%`;
}

function tone(value) {
  const numeric = Number(value);
  if (numeric > 0) return "positive";
  if (numeric < 0) return "negative";
  return "neutral";
}

function formatKst(iso) {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function setSync(mode, text) {
  const dot = $("#sync-dot");
  dot.className = `sync-dot${mode ? ` ${mode}` : ""}`;
  $("#last-updated").textContent = text;
}

function activeMarket() {
  return state.data?.markets.find((market) => market.ticker === state.activeTicker) || state.data?.markets[0];
}

function renderTabs() {
  $("#market-tabs").innerHTML = state.data.markets.map((market, index) => `
    <button class="market-tab ${market.ticker === state.activeTicker ? "active" : ""}" type="button" data-ticker="${escapeHtml(market.ticker)}">
      <span>MARKET 0${index + 1}</span>
      <strong>${escapeHtml(market.name)} · ${escapeHtml(market.ticker)}</strong>
    </button>
  `).join("");
  document.querySelectorAll(".market-tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTicker = button.dataset.ticker;
      renderDashboard();
    });
  });
}

function renderWarnings(market) {
  const warnings = [...(state.data.warnings || []), ...(market.warnings || [])];
  $("#global-warnings").innerHTML = warnings.map((warning) => `
    <div class="warning">${escapeHtml(warning)}</div>
  `).join("");
}

function renderHero(market) {
  const kpi = market.kpis;
  $("#market-hero").innerHTML = `
    <div>
      <p class="eyebrow">LIVE / ${escapeHtml(market.ticker)}</p>
      <h1>${escapeHtml(market.name)}</h1>
    </div>
    <div class="hero-price">
      <strong>${won(kpi.current_price)}</strong>
      <span class="${tone(kpi.price_delta_pct)}">1H ${percent(kpi.price_delta_pct)}</span>
    </div>
  `;
}

function kpiCard(label, value, delta = "", deltaTone = "neutral") {
  return `
    <article class="kpi">
      <span class="kpi-label">${escapeHtml(label)}</span>
      <strong class="kpi-value">${escapeHtml(value)}</strong>
      <span class="kpi-delta ${deltaTone}">${escapeHtml(delta || "—")}</span>
    </article>
  `;
}

function renderKpis(market) {
  const kpi = market.kpis;
  let status = "🟡 대기";
  let statusNote = "신호 감시 중";
  let statusTone = "neutral";
  if (kpi.halted) {
    status = "⛔ 차단";
    statusNote = kpi.halt_reason || "거래 중단";
    statusTone = "negative";
  } else if (kpi.position_held) {
    status = "🟢 정상";
    statusNote = "포지션 보유 중";
    statusTone = "positive";
  }
  $("#kpi-grid").innerHTML = [
    kpiCard("현재가", won(kpi.current_price), percent(kpi.price_delta_pct), tone(kpi.price_delta_pct)),
    kpiCard("배정 예산", won(kpi.budget), `${number(market.settings.position_pct, 1)}% 포지션`),
    kpiCard("봇 운용 자산", won(kpi.bot_market_value), `KRW ${number(kpi.krw_balance)}`),
    kpiCard("누적 손익", won(kpi.cumulative_pnl, true), percent(kpi.cumulative_pnl_pct), tone(kpi.cumulative_pnl)),
    kpiCard("오늘 손익", won(kpi.today_pnl, true), percent(kpi.today_pnl_pct), tone(kpi.today_pnl)),
    kpiCard("승률", `${number(kpi.win_rate, 1)}%`, "실현 거래 기준"),
    kpiCard("거래 상태", status, statusNote, statusTone),
  ].join("");
}

function metric(label, value, note = "", valueTone = "") {
  return `
    <div class="metric-block">
      <label>${escapeHtml(label)}</label>
      <strong class="${valueTone}">${escapeHtml(value)}</strong>
      ${note ? `<small>${escapeHtml(note)}</small>` : ""}
    </div>
  `;
}

function renderPosition(market) {
  const position = market.position;
  if (!position.count) {
    $("#position-panel").innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <h2 class="panel-title">현재 포지션</h2>
          <span class="panel-kicker">NO OPEN POSITION</span>
        </div>
        <div class="empty-state">매수 신호를 감시하고 있습니다.${position.baseline_volume ? ` · 보호 수량 ${number(position.baseline_volume, 8)}` : ""}</div>
      </div>
    `;
    return;
  }

  if (position.mode === "fixed") {
    const rows = position.rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.entry_time)}</td>
        <td>${number(row.entry_price, 2)}</td>
        <td>${number(row.volume, 8)}</td>
        <td>${won(row.invested)}</td>
        <td>${won(row.market_value)}</td>
        <td class="${tone(row.pnl_pct)}">${percent(row.pnl_pct)}</td>
        <td>${number(row.target_price, 2)}</td>
        <td class="${tone(-row.target_gap_pct)}">${percent(row.target_gap_pct)}</td>
        <td>${number(row.stop_price, 2)}</td>
        <td>${percent(row.stop_gap_pct)}</td>
      </tr>
    `).join("");
    $("#position-panel").innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <h2 class="panel-title">보유 포지션 · ${position.count}개</h2>
          <span class="status-chip trend">FIXED +${number(position.tp_pct, 1)}% / ${number(position.sl_pct, 1)}%</span>
        </div>
        <div class="metric-strip">
          ${metric("포지션", `${position.count}개`)}
          ${metric("투자 원금", won(position.total_invested))}
          ${metric("현재 평가", won(position.market_value))}
          ${metric("평가 손익", won(position.unrealized_pnl, true), percent(position.unrealized_pnl_pct), tone(position.unrealized_pnl))}
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>진입시각</th><th>매수가</th><th>수량</th><th>투자원금</th><th>현재평가</th><th>손익률</th><th>목표가</th><th>목표까지</th><th>손절가</th><th>손절까지</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;
    return;
  }

  const isBb = position.strategy_type === "BB";
  const extras = isBb
    ? [
        metric("손절가", won(position.stop_loss_price)),
        metric("목표", "SMA20", "중간선 도달 시 전량 매도"),
        metric("보유 시간", `${number(position.hours_held, 1)}h`, `TIMEOUT까지 ${number(position.timeout_left_hours, 1)}h`),
        metric("진입 ATR", won(position.entry_atr)),
      ]
    : [
        metric("손절가", won(position.stop_loss_price), percent(position.entry_price ? (position.stop_loss_price / position.entry_price - 1) * 100 : 0)),
        metric(`TP1 +${number(position.tp1_pct, 1)}%`, won(position.tp1_price), position.tp1_done ? "✓ 완료" : "대기"),
        metric(`TP2 +${number(position.tp2_pct, 1)}%`, won(position.tp2_price), position.tp2_done ? "✓ 완료" : "대기"),
        metric("진입 후 고점", won(position.highest_price), position.trailing_trigger ? `트레일링 ${won(position.trailing_trigger)}` : "TP1 이후 활성"),
      ];
  $("#position-panel").innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <h2 class="panel-title">현재 포지션</h2>
        <span class="status-chip ${isBb ? "sideways" : "trend"}">${isBb ? "BB MEAN REVERSION" : "TREND FOLLOW"}</span>
      </div>
      <div class="metric-strip">
        ${metric("매수가", won(position.entry_price))}
        ${metric("현재가", won(position.current_price), percent(position.pnl_pct), tone(position.pnl_pct))}
        ${metric("평가 손익", won(position.unrealized_pnl, true), "미실현", tone(position.unrealized_pnl))}
        ${metric("잔량", number(position.remaining_volume, 8), position.entry_time)}
        ${extras.join("")}
      </div>
    </div>
  `;
}

function renderMarketState(market) {
  const marketState = market.market_state;
  if (!marketState.available) {
    $("#market-panel").innerHTML = `
      <div class="panel"><div class="panel-header"><h2 class="panel-title">1H 시장 상태</h2></div><div class="empty-state">${escapeHtml(marketState.message)}</div></div>
    `;
    return;
  }
  const regimeClass = marketState.regime.toLowerCase();
  const labels = { TREND: "추세장", SIDEWAYS: "횡보장", BEAR: "약세장", NEUTRAL: "데이터 부족" };
  const indicators = marketState.indicators;
  const bands = marketState.bands;
  const checks = marketState.checks || [];
  $("#market-panel").innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <h2 class="panel-title">1H 시장 상태 / 매수 조건</h2>
        <span class="panel-kicker">${checks.length ? `${marketState.checks_passed} / ${checks.length} PASSED` : "CAPITAL PRESERVATION"}</span>
      </div>
      <div class="regime-line">
        <span class="status-chip ${regimeClass}">${escapeHtml(marketState.regime)} · ${escapeHtml(labels[marketState.regime] || marketState.regime)}</span>
        <p>${escapeHtml(marketState.regime_reason)}<br>MA200 기울기 ${percent(marketState.regime_metrics.ma200_slope_pct)} · P/MA200 ${percent(marketState.regime_metrics.price_to_ma200_pct)}</p>
      </div>
      <div class="indicator-grid">
        ${metric("MA20", won(indicators.ma20), percent(indicators.ma20 ? (market.kpis.current_price / indicators.ma20 - 1) * 100 : 0))}
        ${metric("MA50", won(indicators.ma50), percent(indicators.ma50 ? (market.kpis.current_price / indicators.ma50 - 1) * 100 : 0))}
        ${metric("MA200", won(indicators.ma200), percent(indicators.ma200 ? (market.kpis.current_price / indicators.ma200 - 1) * 100 : 0))}
        ${metric("RSI (14)", number(indicators.rsi, 1))}
        ${metric("ATR (14)", won(indicators.atr))}
      </div>
      <div class="bands-grid">
        ${metric(`BB 하단 (${bands.period}, ${bands.std}σ)`, won(bands.lower), percent(bands.lower ? (market.kpis.current_price / bands.lower - 1) * 100 : 0))}
        ${metric("BB 중간", won(bands.mid), percent(bands.mid ? (market.kpis.current_price / bands.mid - 1) * 100 : 0))}
        ${metric("BB 상단", won(bands.upper), percent(bands.upper ? (market.kpis.current_price / bands.upper - 1) * 100 : 0))}
      </div>
      ${checks.length ? `<div class="checks">${checks.map((check) => `
        <div class="check ${check.passed ? "passed" : ""}"><i>${check.passed ? "✓" : "·"}</i><span>${escapeHtml(check.label)}</span></div>
      `).join("")}</div>` : `<div class="empty-state">${escapeHtml(marketState.regime)} 상태에서는 신규 매수를 평가하지 않습니다.</div>`}
    </div>
  `;
}

function renderCharts(market) {
  const hasCumulative = market.charts.cumulative.length > 0;
  const hasDaily = market.charts.daily.some((point) => point.value !== 0);
  $("#chart-panel").innerHTML = `
    <div class="panel">
      <div class="panel-header"><h2 class="panel-title">실현 손익</h2><span class="panel-kicker">30 DAY WINDOW</span></div>
      <div class="chart-grid">
        <div class="chart-card"><h3>누적 실현손익</h3>${hasCumulative ? '<canvas id="cumulative-chart" aria-label="누적 실현손익 차트"></canvas>' : '<div class="empty-state">매도 내역이 없습니다.</div>'}</div>
        <div class="chart-card"><h3>일별 손익 · 합계 ${won(market.charts.daily_total, true)}</h3>${hasDaily ? '<canvas id="daily-chart" aria-label="최근 30일 손익 차트"></canvas>' : '<div class="empty-state">최근 30일 실현 손익이 없습니다.</div>'}</div>
      </div>
    </div>
  `;
  requestAnimationFrame(() => {
    if (hasCumulative) drawLineChart($("#cumulative-chart"), market.charts.cumulative);
    if (hasDaily) drawBarChart($("#daily-chart"), market.charts.daily);
  });
}

function canvasContext(canvas) {
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  return { context, width: rect.width, height: rect.height };
}

function chartFrame(context, width, height, values) {
  const padding = { top: 12, right: 10, bottom: 27, left: 55 };
  let min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  if (min === max) { min -= 1; max += 1; }
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const y = (value) => padding.top + (max - value) / (max - min) * plotHeight;
  context.font = '10px "SFMono-Regular", monospace';
  context.strokeStyle = "#2a3035";
  context.fillStyle = "#77848a";
  context.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const value = max - (max - min) * index / 4;
    const lineY = y(value);
    context.beginPath();
    context.moveTo(padding.left, lineY);
    context.lineTo(width - padding.right, lineY);
    context.stroke();
    context.fillText(compactWon(value), 2, lineY + 3);
  }
  return { padding, plotWidth, plotHeight, y };
}

function compactWon(value) {
  const absolute = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (absolute >= 1_000_000) return `${sign}${(absolute / 1_000_000).toFixed(1)}m`;
  if (absolute >= 1_000) return `${sign}${(absolute / 1_000).toFixed(0)}k`;
  return `${Math.round(value)}`;
}

function drawLineChart(canvas, points) {
  const { context, width, height } = canvasContext(canvas);
  const values = points.map((point) => Number(point.value));
  const frame = chartFrame(context, width, height, values);
  const x = (index) => frame.padding.left + (points.length === 1 ? frame.plotWidth / 2 : index / (points.length - 1) * frame.plotWidth);
  const gradient = context.createLinearGradient(0, frame.padding.top, 0, height - frame.padding.bottom);
  gradient.addColorStop(0, "rgba(201,255,53,.25)");
  gradient.addColorStop(1, "rgba(201,255,53,0)");
  context.beginPath();
  points.forEach((point, index) => {
    const px = x(index), py = frame.y(point.value);
    if (index === 0) context.moveTo(px, py); else context.lineTo(px, py);
  });
  context.lineTo(x(points.length - 1), height - frame.padding.bottom);
  context.lineTo(x(0), height - frame.padding.bottom);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();
  context.beginPath();
  points.forEach((point, index) => {
    const px = x(index), py = frame.y(point.value);
    if (index === 0) context.moveTo(px, py); else context.lineTo(px, py);
  });
  context.strokeStyle = "#c9ff35";
  context.lineWidth = 2;
  context.stroke();
  context.fillStyle = "#77848a";
  context.fillText(points[0].time.slice(5, 10), frame.padding.left, height - 7);
  context.textAlign = "right";
  context.fillText(points.at(-1).time.slice(5, 10), width - frame.padding.right, height - 7);
  context.textAlign = "left";
}

function drawBarChart(canvas, points) {
  const { context, width, height } = canvasContext(canvas);
  const values = points.map((point) => Number(point.value));
  const frame = chartFrame(context, width, height, values);
  const slot = frame.plotWidth / points.length;
  const zero = frame.y(0);
  points.forEach((point, index) => {
    const valueY = frame.y(point.value);
    context.fillStyle = point.value < 0 ? "#ff5f68" : "#64e39a";
    context.fillRect(frame.padding.left + index * slot + 1, Math.min(valueY, zero), Math.max(1, slot - 2), Math.max(1, Math.abs(zero - valueY)));
  });
  context.fillStyle = "#77848a";
  context.fillText(points[0].date.slice(5), frame.padding.left, height - 7);
  context.textAlign = "right";
  context.fillText(points.at(-1).date.slice(5), width - frame.padding.right, height - 7);
  context.textAlign = "left";
}

function renderTrades(market) {
  const filters = state.tradeFilters[market.ticker] || { buy: true, sell: true, rows: 50 };
  state.tradeFilters[market.ticker] = filters;
  const filtered = market.trades.filter((row) =>
    (row["종류"] === "매수" && filters.buy) || (row["종류"] === "매도" && filters.sell) || !["매수", "매도"].includes(row["종류"])
  ).slice(0, filters.rows);
  const preferred = ["날짜시간", "종류", "사유", "매수가(원)", "매도가(원)", "수량", "매수금액(원)", "매도금액(원)", "손익(원)", "손익률(%)", "MA20", "MA50", "MA200", "RSI", "ATR"];
  const available = new Set(market.trades.flatMap((row) => Object.keys(row)));
  const columns = preferred.filter((column) => available.has(column));
  const rows = filtered.map((row) => `
    <tr>${columns.map((column) => {
      const value = row[column] ?? "-";
      const className = column === "종류" ? (value === "매수" ? "trade-buy" : value === "매도" ? "trade-sell" : "") : column.includes("손익") ? tone(Number(String(value).replaceAll(",", "").replace("%", ""))) : "";
      return `<td class="${className}">${escapeHtml(value)}</td>`;
    }).join("")}</tr>
  `).join("");
  $("#trade-panel").innerHTML = `
    <div class="panel">
      <div class="panel-header"><h2 class="panel-title">거래 내역</h2><span class="panel-kicker">${market.trades.length} RECORDS</span></div>
      <div class="table-tools">
        <div class="filter-group">
          <label><input id="filter-buy" type="checkbox" ${filters.buy ? "checked" : ""}> 매수</label>
          <label><input id="filter-sell" type="checkbox" ${filters.sell ? "checked" : ""}> 매도</label>
          <label>표시 <select id="filter-rows">${[10, 50, 100, 500].map((count) => `<option value="${count}" ${filters.rows === count ? "selected" : ""}>${count}행</option>`).join("")}</select></label>
        </div>
        <a class="download-link" href="/api/trades/${encodeURIComponent(market.ticker)}/csv">CSV 다운로드 ↓</a>
      </div>
      ${columns.length ? `<div class="table-wrap"><table><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${columns.length}">선택한 조건의 거래가 없습니다.</td></tr>`}</tbody></table></div>` : '<div class="empty-state">거래 내역이 없습니다.</div>'}
    </div>
  `;
  ["buy", "sell"].forEach((type) => {
    $(`#filter-${type}`)?.addEventListener("change", (event) => {
      filters[type] = event.target.checked;
      renderTrades(market);
    });
  });
  $("#filter-rows")?.addEventListener("change", (event) => {
    filters.rows = Number(event.target.value);
    renderTrades(market);
  });
}

function renderLog() {
  $("#log-panel").innerHTML = `
    <div class="panel">
      <button id="log-toggle" class="log-toggle" type="button" aria-expanded="${state.logOpen}">
        <span class="panel-title">최근 로그 · 50줄</span><span>${state.logOpen ? "닫기 ↑" : "열기 ↓"}</span>
      </button>
      ${state.logOpen ? `<pre class="log-output">${escapeHtml(state.data.log)}</pre>` : ""}
    </div>
  `;
  $("#log-toggle").addEventListener("click", () => {
    state.logOpen = !state.logOpen;
    renderLog();
  });
}

function renderFooter(market) {
  const settings = market.settings;
  const mode = settings.exit_strategy === "fixed"
    ? `FIXED +${number(settings.fixed_tp_pct, 1)}% / ${number(settings.fixed_sl_pct, 1)}%`
    : "TREND + BB REGIME DISPATCH";
  $("#market-footer").textContent = `${market.ticker} · BUDGET ${number(settings.budget)} KRW · POSITION ${number(settings.position_pct, 1)}% · ${mode} · CACHE ${state.data.cache_ttl_sec}s`;
}

function renderDashboard() {
  const market = activeMarket();
  if (!market) return;
  renderTabs();
  renderWarnings(market);
  renderHero(market);
  renderKpis(market);
  renderPosition(market);
  renderMarketState(market);
  renderCharts(market);
  renderTrades(market);
  renderLog();
  renderFooter(market);
}

async function loadDashboard(force = false) {
  window.clearTimeout(state.refreshTimer);
  setSync("loading", force ? "거래소 데이터 갱신 중" : "데이터 동기화 중");
  $("#refresh-button").disabled = true;
  try {
    state.data = await apiFetch(`/api/dashboard${force ? "?refresh=true" : ""}`);
    if (!state.activeTicker || !state.data.markets.some((market) => market.ticker === state.activeTicker)) {
      state.activeTicker = state.data.markets[0]?.ticker || null;
    }
    renderDashboard();
    showView("app");
    setSync("", `${formatKst(state.data.generated_at)} KST`);
    state.refreshTimer = window.setTimeout(() => loadDashboard(false), Math.max(5, state.data.refresh_sec) * 1000);
    if (force) showToast("최신 데이터로 갱신했습니다.");
  } catch (error) {
    if (!views.login.hidden) return;
    setSync("error", "동기화 실패");
    showToast(error.message);
    state.refreshTimer = window.setTimeout(() => loadDashboard(false), 15000);
  } finally {
    $("#refresh-button").disabled = false;
  }
}

async function boot() {
  showView("loading");
  try {
    const session = await apiFetch("/api/session");
    if (session.authenticated) {
      await loadDashboard(false);
    } else {
      showView("login");
    }
  } catch (error) {
    showView("login");
    $("#login-error").textContent = error.message;
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#login-error");
  const submit = event.currentTarget.querySelector("button");
  error.textContent = "";
  submit.disabled = true;
  try {
    await apiFetch("/api/login", {
      method: "POST",
      body: JSON.stringify({ password: $("#password").value }),
    });
    $("#password").value = "";
    showView("loading");
    await loadDashboard(false);
  } catch (loginError) {
    error.textContent = loginError.message;
  } finally {
    submit.disabled = false;
  }
});

$("#refresh-button").addEventListener("click", () => loadDashboard(true));
$("#logout-button").addEventListener("click", async () => {
  try { await apiFetch("/api/logout", { method: "POST" }); } catch (_) { /* Cookie is cleared when possible. */ }
  window.clearTimeout(state.refreshTimer);
  state.data = null;
  showView("login");
});

let resizeTimer;
window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    const market = activeMarket();
    if (market && !views.app.hidden) renderCharts(market);
  }, 120);
});

boot();

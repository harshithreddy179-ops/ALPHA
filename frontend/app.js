/* AlphaTrial dashboard */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const COLORS = ["#a78bfa", "#22d3ee", "#34d399", "#fbbf24", "#f472b6", "#60a5fa", "#fb923c", "#c084fc"];
const BH_COLOR = "#8a90a6";
const LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#c9cde0", size: 11, family: "Inter, Segoe UI, system-ui, sans-serif" },
  margin: { l: 55, r: 20, t: 64, b: 40 },
  xaxis: { gridcolor: "#1f2433", zerolinecolor: "#2a3045" },
  yaxis: { gridcolor: "#1f2433", zerolinecolor: "#2a3045" },
  legend: { orientation: "h", y: 1.0, yanchor: "bottom", x: 0, bgcolor: "rgba(0,0,0,0)" },
  hovermode: "x unified",
};
const CONFIG = { displaylogo: false, responsive: true };

const state = { strategies: [], datasets: [] };

// ------------------------------------------------------------------ utils
function plot(id, traces, layout = {}) {
  if (layout.title) layout.title = { x: 0.01, xanchor: "left", y: 0.98, yanchor: "top", ...layout.title };
  if (layout.margin) layout.margin = { ...LAYOUT.margin, ...layout.margin };
  const l = { ...LAYOUT, ...layout,
    xaxis: { ...LAYOUT.xaxis, ...(layout.xaxis || {}) },
    yaxis: { ...LAYOUT.yaxis, ...(layout.yaxis || {}) } };
  Plotly.react(id, traces, l, CONFIG);
}
function toast(msg, ok = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (ok ? " ok" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 5000);
}
function loading(on, text = "Running…") {
  $("#loader").classList.toggle("hidden", !on);
  $("#loader-text").textContent = text;
}
async function api(path, body, text) {
  loading(true, text);
  try {
    const r = await fetch(path, body ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : {});
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : r.statusText);
    return j;
  } catch (e) {
    toast("Error: " + e.message);
    throw e;
  } finally {
    loading(false);
  }
}
const fmt = (v, d = 2, suf = "") => (v === null || v === undefined || Number.isNaN(v)) ? "–" : Number(v).toFixed(d) + suf;
const cls = (v) => v > 0 ? "pos" : v < 0 ? "neg" : "";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function base() {
  return {
    dataset: $("#dataset").value,
    start: $("#start").value || null,
    end: $("#end").value || null,
    capital: +$("#capital").value || 100000,
    costs: { commission_bps: +$("#commission").value, slippage_bps: +$("#slippage").value, fixed_fee: +$("#fee").value },
  };
}
function kpi(label, value, sub = "", klass = "") {
  return `<div class="kpi"><div class="k">${label}</div><div class="v ${klass}">${value}</div><div class="s">${sub}</div></div>`;
}
function table(cols, rows, opts = {}) {
  const head = cols.map((c) => `<th class="${c.left ? "l" : ""}">${c.label}</th>`).join("");
  const body = rows.map((r) => {
    const rc = opts.rowClass ? opts.rowClass(r) : "";
    return `<tr class="${rc}">` + cols.map((c) => {
      const v = c.get ? c.get(r) : r[c.key];
      const k = (c.color ? cls(typeof c.color === "function" ? c.color(r) : v) : "") + (c.left ? " l" : "");
      return `<td class="${k}">${c.fmt ? c.fmt(v, r) : esc(v ?? "–")}</td>`;
    }).join("") + "</tr>";
  }).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
function strategyOptions(sel, { includeCustom = false, includeML = true } = {}) {
  sel.innerHTML = state.strategies
    .filter((s) => includeML || s.key !== "ml")
    .map((s) => `<option value="${s.key}">${s.name}</option>`).join("")
    + (includeCustom ? `<option value="custom">✎ Custom rules (design your own)</option>` : "");
}
function checklist(el, defaults) {
  el.innerHTML = state.strategies.map((s) =>
    `<label><input type="checkbox" value="${s.key}" ${defaults.includes(s.key) ? "checked" : ""}> ${s.name}</label>`).join("")
    + `<label><input type="checkbox" value="custom"> Custom rules</label>`;
}
function checkedSpecs(el) {
  return $$(`#${el.id} input:checked`).map((i) => specFor(i.value));
}
function specFor(key) {
  if (key === "custom") return { key, rules: collectRules(), label: "Custom Rules" };
  if (key === $("#bt-strategy").value) return { key, params: collectParams() };
  return { key };
}

// ------------------------------------------------------------------ init
async function init() {
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => {
    $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
    window.dispatchEvent(new Event("resize"));
  }));

  [state.strategies, state.datasets, state.universe] = await Promise.all(
    [api("/api/strategies"), api("/api/datasets"), api("/api/universe")]);
  renderDatasets(DEFAULT_DATASET);
  strategyOptions($("#bt-strategy"), { includeCustom: true });
  strategyOptions($("#val-strategy"), { includeML: false });
  strategyOptions($("#wf-strategy"), { includeML: false });
  $("#val-strategy").value = "sma_cross";
  $("#wf-strategy").value = "sma_cross";
  checklist($("#cmp-list"), ["sma_cross", "rsi", "momentum", "trend_rsi", "ml"]);
  checklist($("#rg-list"), ["sma_cross", "rsi", "momentum"]);
  checklist($("#cs-list"), ["sma_cross", "ema_cross", "rsi", "momentum", "bollinger"]);
  checklist($("#rp-list"), ["sma_cross", "rsi", "momentum", "trend_rsi", "ml"]);

  $("#bt-strategy").addEventListener("change", renderParams);
  $("#dataset").addEventListener("change", datasetChanged);
  $("#exchange").addEventListener("change", () => {
    const cur = $("#dataset").value;
    const base = cur.startsWith("YF:") ? cur.slice(3).replace(/\.(NS|BO)$/, "") : null;
    renderDatasets(base && !cur.includes("^") ? liveName(base) : cur);
    datasetChanged();
  });
  $("#custom-load").addEventListener("click", loadCustom);
  $("#custom-symbol").addEventListener("keydown", (e) => { if (e.key === "Enter") loadCustom(); });
  $("#mk-run").addEventListener("click", runMarket);
  $("#mk-group").addEventListener("change", runMarket);
  $("#upload").addEventListener("change", uploadCSV);
  $("#bt-run").addEventListener("click", runBacktest);
  $("#cmp-run").addEventListener("click", runCompare);
  $("#val-run").addEventListener("click", runValidate);
  $("#wf-run").addEventListener("click", runWalkForward);
  $("#rg-run").addEventListener("click", runRegimes);
  $("#ml-run").addEventListener("click", runML);
  $("#cs-run").addEventListener("click", runCosts);
  $("#rp-run").addEventListener("click", runReport);
  $("#rp-md").addEventListener("click", downloadReport);
  $$("[data-add]").forEach((b) => b.addEventListener("click", () => addCond(b.dataset.add)));
  $$("[data-preset]").forEach((b) => b.addEventListener("click", () => preset(b.dataset.preset)));

  renderParams();
  preset("dip");
  const okData = await datasetChanged();
  if (!okData) { renderDatasets("ALPHA_TECH"); await datasetChanged(); }
  runBacktest();
}

const DEFAULT_DATASET = "YF:^NSEI";
const exchangeSuffix = () => ($("#exchange").value === "BSE" ? ".BO" : ".NS");
const liveName = (sym) => "YF:" + (sym.startsWith("^") || /\.(NS|BO)$/.test(sym) ? sym : sym + exchangeSuffix());

function renderDatasets(select) {
  const u = state.universe || { indices: [], nifty50: [] };
  const ex = $("#exchange").value;
  const opt = (v, label) => `<option value="${esc(v)}">${esc(label)}</option>`;
  const custom = state.customSymbols || [];
  $("#dataset").innerHTML =
    `<optgroup label="Indices (live)">${u.indices.map((i) => opt("YF:" + i.symbol, `${i.name} (${i.symbol})`)).join("")}</optgroup>`
    + `<optgroup label="NIFTY 50 stocks · ${ex} (live)">${u.nifty50.map((s) => opt(liveName(s.symbol), `${s.symbol}: ${s.name}`)).join("")}</optgroup>`
    + (custom.length ? `<optgroup label="Custom symbols (live)">${custom.map((c) => opt(c, c.slice(3))).join("")}</optgroup>` : "")
    + `<optgroup label="Offline sample data">${state.datasets.filter((d) => !d.uploaded).map((d) => opt(d.name, d.name)).join("")}</optgroup>`
    + (state.datasets.some((d) => d.uploaded) ? `<optgroup label="Uploaded">${state.datasets.filter((d) => d.uploaded).map((d) => opt(d.name, "⬆ " + d.name)).join("")}</optgroup>` : "");
  if (select) {
    if (![...$("#dataset").options].some((o) => o.value === select) && select.startsWith("YF:")) {
      state.customSymbols = [...custom, select];
      return renderDatasets(select);
    }
    $("#dataset").value = select;
  }
}
async function datasetChanged() {
  const name = $("#dataset").value;
  $("#start").value = ""; $("#end").value = "";
  let d = state.datasets.find((x) => x.name === name);
  if (!d) {
    try {
      d = await api("/api/info/" + encodeURIComponent(name), null, `Downloading ${name.slice(3)} price history…`);
    } catch (e) {
      $("#dataset-info").textContent = "Could not load this symbol.";
      return false;
    }
  }
  $("#dataset-info").textContent = `${d.rows} bars · ${d.start} → ${d.end}` + (d.last_close ? ` · last ${Number(d.last_close).toLocaleString("en-IN")}` : "");
  $("#start").min = $("#end").min = d.start;
  $("#start").max = $("#end").max = d.end;
  return true;
}
async function loadCustom() {
  const raw = $("#custom-symbol").value.trim().toUpperCase();
  if (!raw) return;
  renderDatasets(liveName(raw));
  if (await datasetChanged()) { $("#custom-symbol").value = ""; runBacktest(); }
}

// ------------------------------------------------------------------ market
async function runMarket() {
  const group = $("#mk-group").value, ex = $("#exchange").value;
  const d = await api(`/api/market?group=${group}&exchange=${ex}`, null, "Fetching live market data…");
  const rows = d.rows.filter((r) => !r.error);
  const failed = d.rows.filter((r) => r.error);
  $("#mk-title").textContent = `${group === "indices" ? "Indian indices" : "NIFTY 50 · " + ex} (${rows.length} loaded${failed.length ? `, ${failed.length} unavailable` : ""})`;
  const spark = (v) => {
    if (!v || v.length < 2) return "";
    const mn = Math.min(...v), mx = Math.max(...v), w = 90, h = 24;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(h - (x - mn) / ((mx - mn) || 1) * h).toFixed(1)}`).join(" ");
    return `<svg class="spark" width="${w}" height="${h}"><polyline fill="none" stroke="${v[v.length - 1] >= v[0] ? "#34d399" : "#f87171"}" stroke-width="1.5" points="${pts}"/></svg>`;
  };
  const pct = (v) => fmt(v, 2, "%");
  $("#mk-table").innerHTML = table([
    { label: "Symbol", key: "symbol" }, { label: "Name", key: "name", left: true }, { label: "Sector", key: "sector", left: true },
    { label: "Last", key: "close", fmt: (v) => Number(v).toLocaleString("en-IN") },
    { label: "1D", key: "chg_1d", fmt: pct, color: true }, { label: "1W", key: "chg_1w", fmt: pct, color: true },
    { label: "1M", key: "chg_1m", fmt: pct, color: true }, { label: "3M", key: "chg_3m", fmt: pct, color: true },
    { label: "1Y", key: "chg_1y", fmt: pct, color: true }, { label: "Vol 1Y", key: "vol_1y", fmt: pct },
    { label: "52W range", get: (r) => `${Number(r.low_52w).toLocaleString("en-IN")} – ${Number(r.high_52w).toLocaleString("en-IN")}` },
    { label: "60D", key: "spark", fmt: spark },
    { label: "As of", key: "date" },
  ], rows, { rowClass: () => "clickable" })
    + (failed.length ? `<p class="muted small">Unavailable: ${failed.map((f) => esc(f.symbol)).join(", ")}</p>` : "");
  $$("#mk-table tbody tr").forEach((tr, i) => tr.addEventListener("click", () => {
    renderDatasets("YF:" + rows[i].symbol);
    $$("#tabs button").find((b) => b.dataset.tab === "backtest").click();
    datasetChanged().then((ok) => ok && runBacktest());
  }));
  const sorted = [...rows].sort((a, b) => (b.chg_1m ?? 0) - (a.chg_1m ?? 0));
  const movers = sorted.length > 16 ? [...sorted.slice(0, 8), ...sorted.slice(-8)] : sorted;
  plot("mk-movers", [{ type: "bar", orientation: "h", y: movers.map((r) => r.symbol.replace(/\.(NS|BO)$/, "")).reverse(),
    x: movers.map((r) => r.chg_1m).reverse(), marker: { color: movers.map((r) => r.chg_1m >= 0 ? "#34d399" : "#f87171").reverse() } }],
    { title: { text: "1-month return %: top & bottom movers", font: { size: 13 } }, hovermode: "closest", margin: { l: 95 } });
  const bySector = {};
  rows.forEach((r) => { (bySector[r.sector] = bySector[r.sector] || []).push(r.chg_1y); });
  const sec = Object.entries(bySector).map(([k, v]) => [k, v.reduce((a, b) => a + b, 0) / v.length]).sort((a, b) => b[1] - a[1]);
  plot("mk-sector", [{ type: "bar", x: sec.map((s) => s[0]), y: sec.map((s) => s[1]),
    marker: { color: sec.map((s) => s[1] >= 0 ? "#34d399" : "#f87171") } }],
    { title: { text: group === "indices" ? "1-year return % by index" : "Average 1-year return % by sector", font: { size: 13 } },
      hovermode: "closest", margin: { b: 110 } });
  if (group === "indices") plot("mk-sector", [{ type: "bar", x: rows.map((r) => r.name), y: rows.map((r) => r.chg_1y),
    marker: { color: rows.map((r) => r.chg_1y >= 0 ? "#34d399" : "#f87171") } }],
    { title: { text: "1-year return % by index", font: { size: 13 } }, hovermode: "closest", margin: { b: 110 } });
}

async function uploadCSV(e) {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  loading(true, "Uploading…");
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail);
    state.datasets = await (await fetch("/api/datasets")).json();
    renderDatasets(j.name);
    await datasetChanged();
    toast(`Loaded ${j.name}: ${j.rows} rows`, true);
  } catch (err) {
    toast("Upload failed: " + err.message);
  } finally {
    loading(false);
    e.target.value = "";
  }
}

// ------------------------------------------------------------------ params & rule builder
function renderParams() {
  const key = $("#bt-strategy").value;
  const s = state.strategies.find((x) => x.key === key);
  $("#rule-builder").classList.toggle("hidden", key !== "custom");
  $("#bt-desc").textContent = s ? s.description : "Build entry and exit rules from indicators below.";
  $("#bt-params").innerHTML = !s ? "" : s.params.map((p) => {
    if (p.kind === "choice") {
      return `<label>${p.label}<select data-param="${p.name}">${p.grid.map((g) =>
        `<option ${g === p.default ? "selected" : ""}>${g}</option>`).join("")}</select></label>`;
    }
    const step = p.kind === "float" ? "0.01" : "1";
    return `<label>${p.label}<input type="number" step="${step}" data-param="${p.name}" value="${p.default}"></label>`;
  }).join("");
}
function collectParams() {
  const out = {};
  $$("#bt-params [data-param]").forEach((el) => {
    out[el.dataset.param] = el.tagName === "SELECT" ? el.value : Number(el.value);
  });
  return out;
}

const OPERANDS = [
  ["price", "Close"], ["sma", "SMA"], ["ema", "EMA"], ["rsi", "RSI"], ["momentum", "Momentum %"],
  ["volatility", "Volatility %"], ["bb_lower", "Bollinger lower"], ["bb_upper", "Bollinger upper"],
  ["volume", "Volume"], ["volume_sma", "Volume SMA"], ["value", "Number"],
];
const OPS = [">", "<", ">=", "<=", "crosses_above", "crosses_below"];
const needsN = (t) => !["price", "value", "volume"].includes(t);

function operandHTML(side, spec) {
  const t = spec.type;
  return `<span class="opnd" data-side="${side}">
    <select class="ot">${OPERANDS.map(([v, l]) => `<option value="${v}" ${v === t ? "selected" : ""}>${l}</option>`).join("")}</select>
    <input type="number" class="on" value="${t === "value" ? (spec.value ?? 0) : (spec.n ?? 14)}" title="${t === "value" ? "value" : "period"}"
      ${t === "price" || t === "volume" ? 'style="display:none"' : ""}>
  </span>`;
}
function addCond(which, cond) {
  cond = cond || { left: { type: "price" }, op: ">", right: { type: "sma", n: 50 } };
  const div = document.createElement("div");
  div.className = "cond";
  div.innerHTML = operandHTML("l", cond.left)
    + `<select class="op">${OPS.map((o) => `<option ${o === cond.op ? "selected" : ""}>${o}</option>`).join("")}</select>`
    + operandHTML("r", cond.right) + `<button class="x" title="remove">✕</button>`;
  div.querySelector(".x").onclick = () => div.remove();
  div.querySelectorAll(".ot").forEach((sel) => sel.addEventListener("change", () => {
    const inp = sel.nextElementSibling;
    inp.style.display = (sel.value === "price" || sel.value === "volume") ? "none" : "";
    if (sel.value === "value") inp.value = 50;
  }));
  $("#rb-" + which).appendChild(div);
}
function readOperand(span) {
  const t = span.querySelector(".ot").value;
  const n = Number(span.querySelector(".on").value);
  if (t === "value") return { type: "value", value: n };
  return needsN(t) ? { type: t, n } : { type: t };
}
function collectRules() {
  const read = (id) => $$(`#${id} .cond`).map((c) => ({
    left: readOperand(c.querySelector('[data-side="l"]')),
    op: c.querySelector(".op").value,
    right: readOperand(c.querySelector('[data-side="r"]')),
  }));
  return { entry: read("rb-entry"), exit: read("rb-exit"),
           entry_mode: $("#rb-entry-mode").value, exit_mode: $("#rb-exit-mode").value };
}
function preset(name) {
  $("#rb-entry").innerHTML = ""; $("#rb-exit").innerHTML = "";
  const P = {
    golden: {
      entry: [{ left: { type: "sma", n: 50 }, op: "crosses_above", right: { type: "sma", n: 200 } }],
      exit: [{ left: { type: "sma", n: 50 }, op: "crosses_below", right: { type: "sma", n: 200 } }],
    },
    dip: {
      entry: [{ left: { type: "rsi", n: 14 }, op: "<", right: { type: "value", value: 40 } },
              { left: { type: "price" }, op: ">", right: { type: "sma", n: 200 } }],
      exit: [{ left: { type: "rsi", n: 14 }, op: ">", right: { type: "value", value: 70 } },
             { left: { type: "price" }, op: "<", right: { type: "sma", n: 200 } }],
    },
    breakout: {
      entry: [{ left: { type: "momentum", n: 60 }, op: ">", right: { type: "value", value: 5 } },
              { left: { type: "volume" }, op: ">", right: { type: "volume_sma", n: 20 } }],
      exit: [{ left: { type: "momentum", n: 60 }, op: "<", right: { type: "value", value: 0 } }],
    },
  }[name];
  P.entry.forEach((c) => addCond("entry", c));
  P.exit.forEach((c) => addCond("exit", c));
}

// ------------------------------------------------------------------ backtest
async function runBacktest() {
  const key = $("#bt-strategy").value;
  const body = { ...base(), key };
  if (key === "custom") body.rules = collectRules(); else body.params = collectParams();
  const d = await api("/api/backtest", body, "Backtesting…");
  const m = d.result.metrics, b = d.benchmark.metrics, g = d.gross.metrics;
  const dates = d.result.dates;

  $("#bt-kpis").innerHTML = [
    kpi("Total return", fmt(m.total_return, 1, "%"), `B&H ${fmt(b.total_return, 1, "%")}`, cls(m.total_return)),
    kpi("CAGR", fmt(m.cagr, 1, "%"), `B&H ${fmt(b.cagr, 1, "%")}`, cls(m.cagr)),
    kpi("Sharpe", fmt(m.sharpe), `B&H ${fmt(b.sharpe)}`, m.sharpe >= b.sharpe ? "pos" : "neg"),
    kpi("Sortino", fmt(m.sortino), `B&H ${fmt(b.sortino)}`),
    kpi("Max drawdown", fmt(m.max_drawdown, 1, "%"), `B&H ${fmt(b.max_drawdown, 1, "%")}`, "neg"),
    kpi("Win rate", fmt(m.win_rate, 1, "%"), `${m.num_trades} trades`),
    kpi("Profit factor", fmt(m.profit_factor), `avg trade ${fmt(m.avg_trade_pct, 2, "%")}`),
    kpi("Exposure", fmt(m.exposure, 0, "%"), `${fmt(m.trades_per_year, 1)} trades / yr`),
    kpi("Costs paid", "₹" + Number(m.costs_paid).toLocaleString("en-IN"), `${fmt(m.costs_pct_of_capital, 2, "%")} of capital`),
    kpi("Cost drag", fmt(g.total_return - m.total_return, 1, " pp"), `gross ${fmt(g.total_return, 1, "%")}`, "neg"),
  ].join("");

  // Price + overlays + trade markers
  const p = d.price;
  const traces = [{
    type: "candlestick", x: dates, open: p.open, high: p.high, low: p.low, close: p.close,
    name: "Price", increasing: { line: { color: "#34d399" } }, decreasing: { line: { color: "#f87171" } },
    yaxis: "y", showlegend: false,
  }];
  Object.entries(d.overlays.lines || {}).forEach(([name, vals], i) => traces.push({
    x: dates, y: vals, name, mode: "lines", line: { width: 1.4, color: COLORS[(i + 1) % COLORS.length] }, yaxis: "y",
  }));
  const tr = d.result.trades;
  traces.push({
    x: tr.map((t) => t.entry_date), y: tr.map((t) => t.entry_price), mode: "markers", name: "Buy",
    marker: { symbol: "triangle-up", size: 11, color: "#22d3ee", line: { color: "#0b0d14", width: 1 } }, yaxis: "y",
  });
  const closed = tr.filter((t) => !t.open);
  traces.push({
    x: closed.map((t) => t.exit_date), y: closed.map((t) => t.exit_price), mode: "markers", name: "Sell",
    marker: { symbol: "triangle-down", size: 11, color: "#f472b6", line: { color: "#0b0d14", width: 1 } }, yaxis: "y",
    text: closed.map((t) => `P&L ${fmt(t.return_pct, 2)}%`), hoverinfo: "text+x",
  });
  const layout = {
    title: { text: `${d.strategy.name}: price, indicators & signals`, font: { size: 13 } },
    xaxis: { rangeslider: { visible: false } }, showlegend: true,
  };
  const panel = d.overlays.panel;
  if (panel) {
    traces.push({ x: dates, y: panel.values, name: panel.name, line: { color: "#fbbf24", width: 1.2 }, yaxis: "y2" });
    (panel.levels || []).forEach((lv) => traces.push({
      x: [dates[0], dates[dates.length - 1]], y: [lv, lv], mode: "lines", showlegend: false,
      line: { dash: "dot", color: "#8a90a6", width: 1 }, yaxis: "y2", hoverinfo: "skip",
    }));
    layout.yaxis = { domain: [0.32, 1], title: "Price" };
    layout.yaxis2 = { domain: [0, 0.25], gridcolor: "#1f2433", title: panel.name };
  } else {
    traces.push({ x: dates, y: p.volume, type: "bar", name: "Volume", marker: { color: "rgba(138,144,166,.35)" }, yaxis: "y2" });
    layout.yaxis = { domain: [0.22, 1], title: "Price" };
    layout.yaxis2 = { domain: [0, 0.17], gridcolor: "#1f2433", showticklabels: false };
  }
  plot("bt-price", traces, layout);

  plot("bt-equity", [
    { x: dates, y: d.result.equity, name: d.strategy.name + " (net)", line: { color: COLORS[0], width: 2 } },
    { x: dates, y: d.gross.equity, name: "Before costs", line: { color: COLORS[0], width: 1, dash: "dot" } },
    { x: dates, y: d.benchmark.equity, name: "Buy & Hold", line: { color: BH_COLOR, width: 1.5 } },
  ], { title: { text: "Equity curve vs buy-and-hold", font: { size: 13 } }, yaxis: { title: "Portfolio value" } });

  plot("bt-dd", [
    { x: dates, y: d.result.drawdown, name: d.strategy.name, fill: "tozeroy", line: { color: "#f87171", width: 1 } },
    { x: dates, y: d.benchmark.drawdown, name: "Buy & Hold", line: { color: BH_COLOR, width: 1 } },
  ], { title: { text: "Drawdown (%)", font: { size: 13 } } });

  $("#bt-trades").innerHTML = tr.length ? table([
    { label: "#", get: (r) => tr.indexOf(r) + 1 },
    { label: "Entry", key: "entry_date" }, { label: "Exit", key: "exit_date", fmt: (v, r) => v + (r.open ? " (open)" : "") },
    { label: "Entry px", key: "entry_price", fmt: (v) => fmt(v) }, { label: "Exit px", key: "exit_price", fmt: (v) => fmt(v) },
    { label: "Shares", key: "shares" }, { label: "Days", key: "bars_held" },
    { label: "P&L", key: "pnl", fmt: (v) => fmt(v, 0), color: true },
    { label: "Return %", key: "return_pct", fmt: (v) => fmt(v, 2), color: true },
  ], tr) : `<p class="muted">No trades were triggered in this period.</p>`;
}

// ------------------------------------------------------------------ compare
let lastCompare = null;
async function runCompare() {
  const specs = checkedSpecs($("#cmp-list"));
  if (!specs.length) return toast("Pick at least one strategy");
  const d = await api("/api/compare", { ...base(), strategies: specs }, "Comparing strategies…");
  lastCompare = d;
  $("#cmp-table").innerHTML = table([
    { label: "Rank", key: "rank" }, { label: "Strategy", key: "name", left: true },
    { label: "Sharpe", key: "sharpe", fmt: (v) => `<b>${fmt(v)}</b>` },
    { label: "Sortino", key: "sortino", fmt: (v) => fmt(v) },
    { label: "Calmar", key: "calmar", fmt: (v) => fmt(v) },
    { label: "Return %", key: "total_return", fmt: (v) => fmt(v, 1), color: true },
    { label: "CAGR %", key: "cagr", fmt: (v) => fmt(v, 1), color: true },
    { label: "vs B&H (pp)", key: "excess_return", fmt: (v) => fmt(v, 1), color: true },
    { label: "Vol %", key: "volatility", fmt: (v) => fmt(v, 1) },
    { label: "Max DD %", key: "max_drawdown", fmt: (v) => fmt(v, 1) },
    { label: "Win %", key: "win_rate", fmt: (v) => fmt(v, 0) },
    { label: "Trades", key: "num_trades" },
    { label: "Exposure %", key: "exposure", fmt: (v) => fmt(v, 0) },
    { label: "Costs ₹", key: "costs_paid", fmt: (v) => Number(v).toLocaleString("en-IN") },
  ], d.leaderboard, { rowClass: (r) => r.name === "Buy & Hold" ? "bench" : r.rank === 1 ? "highlight" : "" });

  const names = Object.keys(d.series);
  const color = (n, i) => n === "Buy & Hold" ? BH_COLOR : COLORS[i % COLORS.length];
  plot("cmp-equity", names.map((n, i) => ({
    x: d.series[n].dates, y: d.series[n].equity, name: n,
    line: { color: color(n, i), width: n === "Buy & Hold" ? 2 : 1.6, dash: n === "Buy & Hold" ? "dash" : "solid" },
  })), { title: { text: "Equity curves (net of costs)", font: { size: 13 } }, yaxis: { type: "log", title: "Value (log)" } });

  plot("cmp-dd", names.map((n, i) => ({
    x: d.series[n].dates, y: d.series[n].drawdown, name: n, line: { color: color(n, i), width: 1 },
  })), { title: { text: "Drawdowns (%)", font: { size: 13 } } });

  plot("cmp-scatter", d.leaderboard.map((r, i) => ({
    x: [r.volatility], y: [r.cagr], name: r.name, mode: "markers+text", text: [r.name], textposition: "top center",
    marker: { size: 10 + Math.max(0, r.sharpe) * 18, color: r.name === "Buy & Hold" ? BH_COLOR : COLORS[i % COLORS.length], opacity: .85 },
    hovertemplate: `${r.name}<br>Vol %{x:.1f}%<br>CAGR %{y:.1f}%<br>Sharpe ${fmt(r.sharpe)}<extra></extra>`,
  })), { title: { text: "Risk vs return (bubble = Sharpe)", font: { size: 13 } }, showlegend: false, hovermode: "closest",
         xaxis: { title: "Volatility %" }, yaxis: { title: "CAGR %" } });

  const years = d.yearly.map((y) => String(y.year));
  plot("cmp-yearly", [{
    type: "heatmap", x: names, y: years, z: d.yearly.map((y) => names.map((n) => y[n])),
    colorscale: [[0, "#f87171"], [0.5, "#181c29"], [1, "#34d399"]], zmid: 0,
    text: d.yearly.map((y) => names.map((n) => fmt(y[n], 1))), texttemplate: "%{text}", hovertemplate: "%{y} %{x}: %{z:.1f}%<extra></extra>",
  }], { title: { text: "Calendar-year returns (%)", font: { size: 13 } }, yaxis: { autorange: "reversed", type: "category" }, hovermode: "closest", margin: { l: 50, r: 10, t: 64, b: 90 } });

  plot("cmp-corr", [{
    type: "heatmap", x: d.correlation.names, y: d.correlation.names, z: d.correlation.matrix,
    colorscale: "Viridis", zmin: -1, zmax: 1, texttemplate: "%{z:.2f}",
  }], { title: { text: "Daily-return correlation", font: { size: 13 } }, hovermode: "closest", margin: { l: 130, r: 10, t: 64, b: 110 } });
}

// ------------------------------------------------------------------ validation
async function runValidate() {
  const body = { ...base(), key: $("#val-strategy").value, train_ratio: +$("#val-ratio").value, objective: $("#val-objective").value };
  const d = await api("/api/validate", body, "Optimising on training data and testing out of sample…");
  const is = d.in_sample.metrics, os = d.out_of_sample.metrics;
  const explain = {
    Robust: "Performance held up on unseen data, so the edge is likely real.",
    Degraded: "Out-of-sample Sharpe fell by more than half. Part of the in-sample result was luck.",
    Overfit: "Profitable in training, but lost money (negative Sharpe) on unseen data. Classic overfitting.",
    "No Edge": "Even the best in-sample parameters had no positive risk-adjusted return.",
  }[d.verdict];
  $("#val-verdict").innerHTML = `<div class="verdict"><span class="badge ${d.verdict}">${d.verdict}</span>
    <div><b>Best params:</b> ${esc(Object.entries(d.best_params).map(([k, v]) => `${k}=${v}`).join(", "))} (chosen from ${d.combos_tested} combinations)<br>
    <span class="muted">${explain} Sharpe decay: ${fmt(d.sharpe_decay_pct, 1)}%.</span></div></div>`;
  $("#val-kpis").innerHTML = [
    kpi("In-sample Sharpe", fmt(is.sharpe), d.train_period.join(" → ")),
    kpi("Out-of-sample Sharpe", fmt(os.sharpe), d.test_period.join(" → "), os.sharpe > 0 ? "pos" : "neg"),
    kpi("IS return", fmt(is.total_return, 1, "%"), `CAGR ${fmt(is.cagr, 1, "%")}`, cls(is.total_return)),
    kpi("OOS return", fmt(os.total_return, 1, "%"), `CAGR ${fmt(os.cagr, 1, "%")}`, cls(os.total_return)),
    kpi("OOS max DD", fmt(os.max_drawdown, 1, "%"), `IS ${fmt(is.max_drawdown, 1, "%")}`, "neg"),
    kpi("Default params OOS", fmt(d.default_params_oos.sharpe), "Sharpe without tuning"),
    kpi("IS→OOS rank corr.", fmt(d.rank_correlation), "Does IS rank predict OOS?", cls(d.rank_correlation)),
    kpi("PBO", d.pbo ? fmt(d.pbo.pbo, 1, "%") : "–", d.pbo ? d.pbo.interpretation : "", d.pbo && d.pbo.pbo > 50 ? "neg" : "pos"),
  ].join("");

  const isD = d.in_sample.dates, osD = d.out_of_sample.dates;
  const scale = d.in_sample.equity[d.in_sample.equity.length - 1] / (+$("#capital").value || 100000);
  plot("val-equity", [
    { x: isD, y: d.in_sample.equity, name: "In-sample (optimised)", line: { color: COLORS[0], width: 2 } },
    { x: osD, y: d.out_of_sample.equity.map((v) => v * scale), name: "Out-of-sample (frozen params)", line: { color: COLORS[1], width: 2 } },
  ], {
    title: { text: "Train → test equity (test segment chained to training end value)", font: { size: 13 } },
    shapes: [{ type: "rect", xref: "x", yref: "paper", x0: osD[0], x1: osD[osD.length - 1], y0: 0, y1: 1, fillcolor: "rgba(34,211,238,.06)", line: { width: 0 } }],
    annotations: [{ x: osD[0], y: 1, yref: "paper", text: "unseen data →", showarrow: false, xanchor: "left", font: { color: "#22d3ee" } }],
  });

  const sc = d.scatter;
  const lim = [Math.min(...sc.map((s) => Math.min(s.is_sharpe, s.oos_sharpe))) - .1, Math.max(...sc.map((s) => Math.max(s.is_sharpe, s.oos_sharpe))) + .1];
  plot("val-scatter", [
    { x: sc.map((s) => s.is_sharpe), y: sc.map((s) => s.oos_sharpe), mode: "markers", text: sc.map((s) => s.params),
      marker: { color: COLORS[0], size: 7, opacity: .7 }, name: "Parameter sets", hovertemplate: "%{text}<br>IS %{x:.2f} → OOS %{y:.2f}<extra></extra>" },
    { x: [sc[0].is_sharpe], y: [sc[0].oos_sharpe], mode: "markers", name: "Chosen (best IS)", marker: { color: "#fbbf24", size: 14, symbol: "star" } },
    { x: lim, y: lim, mode: "lines", name: "IS = OOS", line: { dash: "dot", color: BH_COLOR } },
  ], { title: { text: "In-sample vs out-of-sample Sharpe, every combination", font: { size: 13 } }, hovermode: "closest",
       xaxis: { title: "In-sample Sharpe" }, yaxis: { title: "Out-of-sample Sharpe" } });

  if (d.heatmap) {
    plot("val-heat", [{ type: "heatmap", x: d.heatmap.x.map(String), y: d.heatmap.y.map(String), z: d.heatmap.z,
      colorscale: [[0, "#f87171"], [0.5, "#fbbf24"], [1, "#34d399"]], texttemplate: "%{z:.2f}", hovertemplate: `${d.heatmap.x_name}=%{x}, ${d.heatmap.y_name}=%{y}: Sharpe %{z:.2f}<extra></extra>` }],
      { title: { text: "In-sample Sharpe surface (smooth plateau = robust, isolated spike = fragile)", font: { size: 12 } },
        xaxis: { title: d.heatmap.x_name, type: "category" }, yaxis: { title: d.heatmap.y_name, type: "category" }, hovermode: "closest" });
  } else Plotly.purge("val-heat");

  if (d.pbo) {
    const bins = { start: Math.floor(Math.min(...d.pbo.logits)), end: Math.ceil(Math.max(...d.pbo.logits)) + 0.25, size: 0.25 };
    plot("val-pbo", [
      { type: "histogram", x: d.pbo.logits.filter((l) => l <= 0), xbins: bins, marker: { color: "#f87171" }, name: "IS winner below OOS median" },
      { type: "histogram", x: d.pbo.logits.filter((l) => l > 0), xbins: bins, marker: { color: "#34d399" }, name: "IS winner above OOS median" }],
      { title: { text: `Probability of Backtest Overfitting = ${fmt(d.pbo.pbo, 1)}% (${d.pbo.splits} CSCV splits)`, font: { size: 13 } },
        xaxis: { title: "logit of the IS-best config's OOS rank" }, bargap: .05, barmode: "overlay", hovermode: "closest",
        shapes: [{ type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1, line: { color: "#fbbf24", dash: "dash" } }] });
  } else Plotly.purge("val-pbo");

  $("#val-top").innerHTML = table([
    { label: "Params", key: "params" }, { label: "IS Sharpe", key: "sharpe", fmt: (v) => fmt(v) },
    { label: "IS Return %", key: "total_return", fmt: (v) => fmt(v, 1), color: true },
    { label: "Max DD %", key: "max_drawdown", fmt: (v) => fmt(v, 1) }, { label: "Trades", key: "num_trades" },
  ], d.top_in_sample);
}

// ------------------------------------------------------------------ walk-forward
async function runWalkForward() {
  const body = { ...base(), key: $("#wf-strategy").value, train_days: +$("#wf-train").value,
    test_days: +$("#wf-test").value, anchored: $("#wf-anchored").checked };
  const d = await api("/api/walkforward", body, "Running walk-forward optimisation…");
  const s = d.summary, b = d.benchmark.metrics;
  $("#wf-kpis").innerHTML = [
    kpi("Verdict", `<span class="badge ${s.verdict}">${s.verdict}</span>`, `${s.n_windows} windows`),
    kpi("OOS return", fmt(s.oos_total_return, 1, "%"), `B&H ${fmt(b.total_return, 1, "%")}`, cls(s.oos_total_return)),
    kpi("OOS Sharpe", fmt(s.oos_sharpe), `B&H ${fmt(b.sharpe)}`, s.oos_sharpe >= b.sharpe ? "pos" : "neg"),
    kpi("OOS CAGR", fmt(s.oos_cagr, 1, "%"), "", cls(s.oos_cagr)),
    kpi("OOS max DD", fmt(s.oos_max_drawdown, 1, "%"), `B&H ${fmt(b.max_drawdown, 1, "%")}`, "neg"),
    kpi("Mean IS → OOS Sharpe", `${fmt(s.mean_is_sharpe)} → ${fmt(s.mean_oos_sharpe)}`, "per window"),
    kpi("WF efficiency", fmt(s.walk_forward_efficiency, 0, "%"), "OOS / IS annualised return", (s.walk_forward_efficiency ?? 0) > 50 ? "pos" : "neg"),
    kpi("Profitable windows", fmt(s.pct_windows_profitable, 0, "%"), `${s.distinct_param_sets} distinct param sets`),
  ].join("");
  plot("wf-equity", [
    { x: d.dates, y: d.equity, name: "Walk-forward OOS equity", line: { color: COLORS[1], width: 2 } },
    { x: d.benchmark.dates, y: d.benchmark.equity, name: "Buy & Hold", line: { color: BH_COLOR, dash: "dash" } },
  ], { title: { text: "Stitched out-of-sample equity", font: { size: 13 } },
       shapes: d.windows.map((w, i) => ({ type: "rect", xref: "x", yref: "paper", x0: w.test[0], x1: w.test[1], y0: 0, y1: 1,
         fillcolor: i % 2 ? "rgba(167,139,250,.05)" : "rgba(0,0,0,0)", line: { width: 0 } })) });
  const lbl = d.windows.map((w) => w.test[0]);
  plot("wf-bars", [
    { type: "bar", x: lbl, y: d.windows.map((w) => w.is_sharpe), name: "In-sample Sharpe", marker: { color: COLORS[0] } },
    { type: "bar", x: lbl, y: d.windows.map((w) => w.oos_sharpe), name: "Out-of-sample Sharpe", marker: { color: COLORS[1] } },
  ], { title: { text: "In-sample vs out-of-sample Sharpe per window", font: { size: 13 } }, barmode: "group", xaxis: { type: "category" } });
  $("#wf-table").innerHTML = table([
    { label: "Train", get: (w) => w.train.join(" → ") }, { label: "Test", get: (w) => w.test.join(" → "), left: true },
    { label: "Chosen params", key: "params" },
    { label: "IS Sharpe", key: "is_sharpe", fmt: (v) => fmt(v) }, { label: "OOS Sharpe", key: "oos_sharpe", fmt: (v) => fmt(v), color: true },
    { label: "IS Ret %", key: "is_return", fmt: (v) => fmt(v, 1) }, { label: "OOS Ret %", key: "oos_return", fmt: (v) => fmt(v, 1), color: true },
    { label: "OOS trades", key: "oos_trades" },
  ], d.windows);
}

// ------------------------------------------------------------------ regimes
const REGIME_COLORS = {
  "Bull / Low Vol": "#34d399", "Bull / High Vol": "#a3e635", "Sideways / Low Vol": "#60a5fa",
  "Sideways / High Vol": "#fbbf24", "Bear / Low Vol": "#fb923c", "Bear / High Vol": "#f87171",
  Bull: "#34d399", Sideways: "#fbbf24", Bear: "#f87171", Unknown: "#4b5063",
};
async function runRegimes() {
  const specs = checkedSpecs($("#rg-list"));
  const d = await api("/api/regimes", { ...base(), strategies: specs, method: $("#rg-method").value }, "Classifying regimes…");
  const regimes = [...new Set(d.labels)].filter((r) => r && r !== "Unknown" && !String(r).includes("Unknown"));
  const traces = [{ x: d.dates, y: d.close, name: "Close", line: { color: "#c9cde0", width: 1 }, hoverinfo: "skip", showlegend: false }];
  regimes.forEach((r) => traces.push({
    x: d.dates.filter((_, i) => d.labels[i] === r), y: d.close.filter((_, i) => d.labels[i] === r),
    mode: "markers", name: r, marker: { size: 4, color: REGIME_COLORS[r] || "#a78bfa" },
  }));
  plot("rg-price", traces, { title: { text: "Price coloured by detected regime", font: { size: 13 } }, hovermode: "closest" });

  const perf = d.performance;
  plot("rg-bars", d.strategies.map((s, i) => ({
    type: "bar", name: s, x: perf.map((p) => p.regime), y: perf.map((p) => p[s] ? p[s].ann_return : null),
    marker: { color: s === "Buy & Hold" ? BH_COLOR : COLORS[i % COLORS.length] },
  })), { title: { text: "Annualised return by regime (%)", font: { size: 13 } }, barmode: "group", margin: { l: 55, r: 10, t: 64, b: 90 } });
  plot("rg-dist", [{ type: "pie", labels: Object.keys(d.distribution), values: Object.values(d.distribution), hole: .5,
    marker: { colors: Object.keys(d.distribution).map((k) => REGIME_COLORS[k] || "#a78bfa") } }],
    { title: { text: "Time spent in each regime", font: { size: 13 } }, hovermode: "closest" });
  $("#rg-table").innerHTML = table([
    { label: "Regime", key: "regime" }, { label: "Days", key: "days" }, { label: "% time", key: "pct_time", fmt: (v) => fmt(v, 1) },
    ...d.strategies.map((s) => ({ label: s, get: (r) => r[s], fmt: (v) => v && v.ann_return !== null ?
      `<span class="${cls(v.ann_return)}">${fmt(v.ann_return, 1)}%</span> · ${fmt(v.sharpe)}` : "–" })),
  ], perf);
}

// ------------------------------------------------------------------ ML
async function runML() {
  const body = { ...base(), model: $("#ml-model").value, threshold: +$("#ml-threshold").value,
    train_window: +$("#ml-window").value, retrain_every: +$("#ml-retrain").value };
  const d = await api("/api/ml", body, "Training walk-forward model (random forest / boosting can take ~10s)…");
  const m = d.backtest.metrics, b = d.benchmark.metrics;
  const edge = d.accuracy - d.baseline_accuracy;
  const msg = edge > 1 ? ["Robust", "The model beats the naive baseline out of sample."]
    : edge > -0.5 ? ["Degraded", "Accuracy is close to the baseline (always guessing the majority direction). Daily direction is mostly noise, which is expected for efficient markets."]
    : ["Overfit", "The model does worse than the naive baseline out of sample."];
  $("#ml-verdict").innerHTML = `<div class="verdict"><span class="badge ${msg[0]}">Edge ${edge >= 0 ? "+" : ""}${fmt(edge, 2)} pp</span>
    <div>${msg[1]}<br><span class="muted">${d.fits} walk-forward fits · ${d.oos_predictions} out-of-sample predictions</span></div></div>`;
  $("#ml-kpis").innerHTML = [
    kpi("OOS accuracy", fmt(d.accuracy, 1, "%"), `baseline ${fmt(d.baseline_accuracy, 1, "%")}`, edge > 0 ? "pos" : "neg"),
    kpi("Precision (up)", fmt(d.precision_up, 1, "%"), `up days ${fmt(d.up_day_ratio, 1, "%")}`),
    kpi("ROC AUC", fmt(d.auc, 3), "0.5 = random", d.auc > 0.5 ? "pos" : "neg"),
    kpi("Strategy Sharpe", fmt(m.sharpe), `B&H ${fmt(b.sharpe)}`, m.sharpe >= b.sharpe ? "pos" : "neg"),
    kpi("Strategy return", fmt(m.total_return, 1, "%"), `B&H ${fmt(b.total_return, 1, "%")}`, cls(m.total_return)),
    kpi("Max DD", fmt(m.max_drawdown, 1, "%"), `B&H ${fmt(b.max_drawdown, 1, "%")}`, "neg"),
    kpi("Trades", m.num_trades, `exposure ${fmt(m.exposure, 0, "%")}`),
  ].join("");
  const imp = Object.entries(d.feature_importance).reverse();
  plot("ml-imp", [{ type: "bar", orientation: "h", x: imp.map((x) => x[1]), y: imp.map((x) => x[0]), marker: { color: COLORS[0] } }],
    { title: { text: "Feature importance (avg over fits)", font: { size: 13 } }, margin: { l: 95, r: 10, t: 50, b: 30 }, hovermode: "closest" });
  plot("ml-cal", [
    { type: "bar", x: d.calibration.map((c) => c.bucket), y: d.calibration.map((c) => c.hit_rate), name: "Actual up-rate",
      marker: { color: COLORS[1] }, text: d.calibration.map((c) => `n=${c.count}`), textposition: "outside" },
    { x: d.calibration.map((c) => c.bucket), y: d.calibration.map(() => d.up_day_ratio), mode: "lines", name: "Base rate", line: { dash: "dot", color: BH_COLOR } },
  ], { title: { text: "Calibration: actual up-rate by predicted P(up) bucket", font: { size: 13 } }, yaxis: { title: "% days up" }, xaxis: { type: "category" } });
  plot("ml-proba", [
    { x: d.dates, y: d.proba, name: "P(next close up)", line: { color: COLORS[3], width: 1 } },
    { x: [d.dates[0], d.dates[d.dates.length - 1]], y: [body.threshold, body.threshold], mode: "lines", name: "Entry threshold", line: { dash: "dash", color: "#34d399" } },
    { x: [d.dates[0], d.dates[d.dates.length - 1]], y: [1 - body.threshold, 1 - body.threshold], mode: "lines", name: "Exit threshold", line: { dash: "dash", color: "#f87171" } },
  ], { title: { text: "Out-of-sample predicted probabilities", font: { size: 13 } } });
  plot("ml-equity", [
    { x: d.backtest.dates, y: d.backtest.equity, name: "ML strategy", line: { color: COLORS[0], width: 2 } },
    { x: d.backtest.dates, y: d.benchmark.equity, name: "Buy & Hold", line: { color: BH_COLOR, dash: "dash" } },
  ], { title: { text: "ML strategy equity (net of costs)", font: { size: 13 } } });
}

// ------------------------------------------------------------------ costs
async function runCosts() {
  const specs = checkedSpecs($("#cs-list"));
  if (!specs.length) return toast("Pick at least one strategy");
  const d = await api("/api/costs", { ...base(), strategies: specs }, "Sweeping cost levels…");
  const mk = (key) => [
    ...d.strategies.map((s, i) => ({ x: d.levels, y: s.rows.map((r) => r[key]), name: s.name, mode: "lines+markers", line: { color: COLORS[i % COLORS.length] } })),
    { x: d.levels, y: d.buy_and_hold.map((r) => r[key]), name: "Buy & Hold", mode: "lines", line: { color: BH_COLOR, dash: "dash" } },
  ];
  plot("cs-return", mk("total_return"), { title: { text: "Total return (%) vs round-trip cost", font: { size: 13 } }, xaxis: { title: "Round-trip cost (bps)" },
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "#f87171", width: 1 } }] });
  plot("cs-sharpe", mk("sharpe"), { title: { text: "Sharpe ratio vs round-trip cost", font: { size: 13 } }, xaxis: { title: "Round-trip cost (bps)" } });
  const bh0 = d.buy_and_hold[0].total_return;
  $("#cs-table").innerHTML = table([
    { label: "Strategy", key: "name" },
    { label: "Trades", get: (s) => s.rows[0].trades },
    { label: "Turnover / yr", key: "turnover", fmt: (v) => fmt(v, 1) },
    { label: "Gross return % (0 bps)", get: (s) => s.rows[0].total_return, fmt: (v) => fmt(v, 1), color: true },
    { label: "Return lost at 10 bps (pp)", key: "return_lost_at_10bps", fmt: (v) => fmt(v, 1) },
    { label: "Break-even cost (bps)", key: "break_even_bps", fmt: (v) => v === null ? "> 100" : fmt(v, 1) },
    { label: "Beats B&H until (bps)", key: "beats_bh_until_bps", fmt: (v, s) => s.rows[0].total_return <= bh0 ? "never" : v === null ? "> 100" : fmt(v, 1) },
  ], d.strategies);
}

// ------------------------------------------------------------------ report
function reportBody() {
  return { ...base(), strategies: checkedSpecs($("#rp-list")), validation: $("#rp-val").checked };
}
async function runReport() {
  const body = reportBody();
  if (!body.strategies.length) return toast("Pick at least one strategy");
  const r = await api("/api/report", body, "Building report (includes out-of-sample tests)…");
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const lb = table([
    { label: "#", key: "rank" }, { label: "Strategy", key: "name", left: true }, { label: "Sharpe", key: "sharpe", fmt: (v) => `<b>${fmt(v)}</b>` },
    { label: "Return %", key: "total_return", fmt: (v) => fmt(v, 1), color: true }, { label: "CAGR %", key: "cagr", fmt: (v) => fmt(v, 1), color: true },
    { label: "Max DD %", key: "max_drawdown", fmt: (v) => fmt(v, 1) }, { label: "Win %", key: "win_rate", fmt: (v) => fmt(v, 0) },
    { label: "Trades", key: "num_trades" }, { label: "Exposure %", key: "exposure", fmt: (v) => fmt(v, 0) },
  ], r.leaderboard, { rowClass: (x) => x.name === "Buy & Hold" ? "bench" : x.rank === 1 ? "highlight" : "" });
  const sections = r.sections.map((s) => {
    const v = s.validation;
    const vline = v && v.is_sharpe !== undefined
      ? `<p><span class="badge ${v.verdict}">${v.verdict}</span> In-sample Sharpe ${fmt(v.is_sharpe)} → out-of-sample ${fmt(v.oos_sharpe)}${v.pbo !== null && v.pbo !== undefined ? ` · PBO ${fmt(v.pbo, 1)}%` : ""} · best params ${esc(Object.entries(v.best_params).map(([k, x]) => `${k}=${x}`).join(", "))}</p>` : "";
    const cost = s.cost ? `<p class="muted">Break-even round-trip cost: ${s.cost.break_even_bps === null ? "> 100" : fmt(s.cost.break_even_bps, 1)} bps · turnover ${fmt(s.cost.turnover, 1)} position changes / yr</p>` : "";
    return `<div class="card"><h2>${esc(s.name)}</h2>${vline}${cost}
      <div class="sw"><div class="strengths"><h4>Strengths</h4><ul>${s.strengths.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>None identified</li>"}</ul></div>
      <div class="weaknesses"><h4>Weaknesses</h4><ul>${s.weaknesses.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>None identified</li>"}</ul></div></div></div>`;
  }).join("");
  $("#rp-body").innerHTML = `
    <div class="card"><h2>Strategy comparison report: ${esc(r.dataset)}</h2>
      <p class="muted">${r.period[0]} → ${r.period[1]} · capital ${Number(r.capital).toLocaleString()} · commission ${r.costs.commission_bps} bps + slippage ${r.costs.slippage_bps} bps per side</p>
      <h3>Executive summary</h3><ul class="summary">${r.summary.map((s) => `<li>${md(s)}</li>`).join("")}</ul></div>
    <div class="card"><h3>Leaderboard (ranked by Sharpe)</h3><div class="table-wrap">${lb}</div></div>
    ${sections}
    <div class="card"><h3>Methodology &amp; bias controls</h3><ul>${r.methodology.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
    <h3>Limitations</h3><ul><li>Historical performance does not guarantee future results.</li>
    <li>Fills assume the next open plus fixed slippage; real liquidity and market impact may differ.</li>
    <li>Long-only, single-asset; dividends, borrow costs and taxes are not modelled.</li></ul></div>`;
}
async function downloadReport() {
  const body = reportBody();
  if (!body.strategies.length) return toast("Pick at least one strategy");
  loading(true, "Building report…");
  try {
    const r = await fetch("/api/report.md", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json()).detail);
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${body.dataset}_alphatrial_report.md`;
    a.click();
  } catch (e) { toast("Error: " + e.message); } finally { loading(false); }
}

init();

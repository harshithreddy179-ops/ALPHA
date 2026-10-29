/* AlphaTrial dashboard */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const COLORS = ["#4f46e5", "#0d9488", "#d97706", "#db2777", "#2563eb", "#7c3aed"];
const BH_COLOR = "#9ca3af";
const UP = "#15803d", DOWN = "#c62828";
const LAYOUT = {
  paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff",
  font: { color: "#374151", size: 14, family: "Segoe UI, system-ui, Roboto, Arial, sans-serif" },
  margin: { l: 95, r: 20, t: 20, b: 55 },
  xaxis: { gridcolor: "#eef0f3", zerolinecolor: "#d1d5db" },
  yaxis: { gridcolor: "#eef0f3", zerolinecolor: "#d1d5db" },
  legend: { orientation: "h", y: 1.02, yanchor: "bottom", x: 0 },
  hovermode: "x unified",
};
const CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] };

const state = { strategies: [], datasets: [], marketLoaded: false };

// ------------------------------------------------------------------ helpers
function plot(id, traces, layout = {}) {
  // Plotly 4 expects axis titles as {text}.
  for (const k of Object.keys(layout)) {
    if (/^[xy]axis/.test(k) && typeof layout[k].title === "string") layout[k].title = { text: layout[k].title };
  }
  const l = { ...LAYOUT, ...layout,
    margin: { ...LAYOUT.margin, ...(layout.margin || {}) },
    xaxis: { ...LAYOUT.xaxis, ...(layout.xaxis || {}) },
    yaxis: { ...LAYOUT.yaxis, ...(layout.yaxis || {}) } };
  Plotly.react(id, traces, l, CONFIG);
}
function toast(msg, ok = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (ok ? " ok" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 6000);
}
function loading(on, text = "Working…") {
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
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : r.statusText);
    return j;
  } catch (e) {
    toast("Something went wrong: " + e.message);
    throw e;
  } finally {
    loading(false);
  }
}
const fmt = (v, d = 2, suf = "") => (v === null || v === undefined || Number.isNaN(v)) ? "–" : Number(v).toFixed(d) + suf;
const pct = (v, d = 1) => fmt(v, d, "%");
const signed = (v, d = 1) => (v > 0 ? "+" : "") + pct(v, d);
const rupees = (v) => "₹" + Math.round(v).toLocaleString("en-IN");
const cls = (v) => v > 0 ? "pos" : v < 0 ? "neg" : "";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const verdictClass = (v) => String(v).replace(/\s/g, "");

function base() {
  return {
    dataset: $("#dataset").value,
    start: $("#start").value || null,
    end: $("#end").value || null,
    capital: +$("#capital").value || 100000,
    costs: { commission_bps: +$("#commission").value, slippage_bps: +$("#slippage").value, fixed_fee: 0 },
  };
}
function kpi(label, value, sub = "", klass = "") {
  return `<div class="kpi"><div class="k">${label}</div><div class="v ${klass}">${value}</div><div class="s">${sub}</div></div>`;
}
function verdictBox(verdict, text) {
  return `<div class="verdict ${verdictClass(verdict)}"><span class="badge">${esc(verdict)}</span><span>${text}</span></div>`;
}
function table(cols, rows, opts = {}) {
  const head = cols.map((c) => `<th class="${c.left ? "l" : ""}">${c.label}</th>`).join("");
  const body = rows.map((r) => {
    const rc = opts.rowClass ? opts.rowClass(r) : "";
    return `<tr class="${rc}">` + cols.map((c) => {
      const v = c.get ? c.get(r) : r[c.key];
      const k = (c.color ? cls(v) : "") + (c.left ? " l" : "");
      return `<td class="${k}">${c.fmt ? c.fmt(v, r) : esc(v ?? "–")}</td>`;
    }).join("") + "</tr>";
  }).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
function strategyOptions(sel, { includeCustom = false, includeML = true } = {}) {
  sel.innerHTML = state.strategies
    .filter((s) => includeML || s.key !== "ml")
    .map((s) => `<option value="${s.key}">${s.name}</option>`).join("")
    + (includeCustom ? `<option value="custom">My own rules</option>` : "");
}
function checklist(el, defaults) {
  el.innerHTML = state.strategies.map((s) =>
    `<label><input type="checkbox" value="${s.key}" ${defaults.includes(s.key) ? "checked" : ""}> ${s.name}</label>`).join("");
}
function checkedSpecs(el) {
  return $$(`#${el.id} input:checked`).map((i) =>
    i.value === $("#bt-strategy").value ? { key: i.value, params: collectParams() } : { key: i.value });
}

// ------------------------------------------------------------------ start-up
async function init() {
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  [state.strategies, state.datasets, state.universe] = await Promise.all(
    [api("/api/strategies"), api("/api/datasets"), api("/api/universe")]);
  renderDatasets(DEFAULT_DATASET);
  strategyOptions($("#bt-strategy"), { includeCustom: true });
  strategyOptions($("#val-strategy"), { includeML: false });
  $("#val-strategy").value = "sma_cross";
  checklist($("#cmp-list"), ["sma_cross", "rsi", "momentum"]);
  checklist($("#rp-list"), ["sma_cross", "rsi", "momentum"]);

  $("#settings-toggle").addEventListener("click", () => $("#settings").classList.toggle("hidden"));
  $("#bt-strategy").addEventListener("change", renderParams);
  $("#dataset").addEventListener("change", async () => { if (await datasetChanged()) rerunCurrent(); });
  $("#exchange").addEventListener("change", async () => {
    const cur = $("#dataset").value;
    const sym = cur.startsWith("YF:") && !cur.includes("^") ? cur.slice(3).replace(/\.(NS|BO)$/, "") : null;
    renderDatasets(sym ? liveName(sym) : cur);
    state.marketLoaded = false;
    if (await datasetChanged()) rerunCurrent();
  });
  $("#custom-load").addEventListener("click", loadCustom);
  $("#custom-symbol").addEventListener("keydown", (e) => { if (e.key === "Enter") loadCustom(); });
  $("#upload").addEventListener("change", uploadCSV);
  $("#mk-run").addEventListener("click", runMarket);
  $("#mk-group").addEventListener("change", runMarket);
  $("#bt-run").addEventListener("click", runBacktest);
  $("#cmp-run").addEventListener("click", runCompare);
  $("#val-run").addEventListener("click", runValidate);
  $("#ml-run").addEventListener("click", runML);
  $("#rp-run").addEventListener("click", runReport);
  $("#rp-md").addEventListener("click", downloadReport);
  $$("[data-add]").forEach((b) => b.addEventListener("click", () => addCond(b.dataset.add)));
  $$("[data-preset]").forEach((b) => b.addEventListener("click", () => preset(b.dataset.preset)));

  renderParams();
  preset("dip");
  if (!(await datasetChanged())) { renderDatasets("ALPHA_TECH"); await datasetChanged(); }
  runBacktest();
}

function showTab(name) {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  window.dispatchEvent(new Event("resize"));
  if (name === "market" && !state.marketLoaded) runMarket();
}
function currentTab() { return $("#tabs button.active").dataset.tab; }
function rerunCurrent() { if (currentTab() === "backtest") runBacktest(); }

// ------------------------------------------------------------------ data selection
const DEFAULT_DATASET = "YF:^NSEI";
const exchangeSuffix = () => ($("#exchange").value === "BSE" ? ".BO" : ".NS");
const liveName = (sym) => "YF:" + (sym.startsWith("^") || /\.(NS|BO)$/.test(sym) ? sym : sym + exchangeSuffix());

function renderDatasets(select) {
  const u = state.universe || { indices: [], nifty50: [] };
  const opt = (v, label) => `<option value="${esc(v)}">${esc(label)}</option>`;
  const custom = state.customSymbols || [];
  const uploaded = state.datasets.filter((d) => d.uploaded);
  $("#dataset").innerHTML =
    `<optgroup label="Indices">${u.indices.map((i) => opt("YF:" + i.symbol, i.name)).join("")}</optgroup>`
    + `<optgroup label="NIFTY 50 stocks">${u.nifty50.map((s) => opt(liveName(s.symbol), `${s.name} (${s.symbol})`)).join("")}</optgroup>`
    + (custom.length ? `<optgroup label="Searched">${custom.map((c) => opt(c, c.slice(3))).join("")}</optgroup>` : "")
    + (uploaded.length ? `<optgroup label="Uploaded">${uploaded.map((d) => opt(d.name, d.name)).join("")}</optgroup>` : "")
    + `<optgroup label="Offline sample data">${state.datasets.filter((d) => !d.uploaded).map((d) => opt(d.name, d.name)).join("")}</optgroup>`;
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
      d = await api("/api/info/" + encodeURIComponent(name), null, "Downloading prices…");
    } catch (e) {
      $("#dataset-info").textContent = "Couldn't load this symbol. Check the spelling or try the other exchange.";
      return false;
    }
  }
  const label = $("#dataset").selectedOptions[0]?.textContent || name;
  $("#dataset-info").innerHTML = `<b>${esc(label)}</b> · ${d.start} to ${d.end}`
    + (d.last_close ? ` · last price ₹${Number(d.last_close).toLocaleString("en-IN")}` : "")
    + (d.note ? `<br><span class="small">${esc(d.note)}</span>` : "");
  $("#start").min = $("#end").min = d.start;
  $("#start").max = $("#end").max = d.end;
  return true;
}
async function loadCustom() {
  const raw = $("#custom-symbol").value.trim().toUpperCase();
  if (!raw) return;
  renderDatasets(liveName(raw));
  if (await datasetChanged()) { $("#custom-symbol").value = ""; rerunCurrent(); }
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
    toast(`Loaded ${j.name} (${j.rows} days)`, true);
  } catch (err) {
    toast("Upload failed: " + err.message);
  } finally {
    loading(false);
    e.target.value = "";
  }
}

// ------------------------------------------------------------------ market
async function runMarket() {
  const group = $("#mk-group").value, ex = $("#exchange").value;
  const d = await api(`/api/market?group=${group}&exchange=${ex}`, null, "Loading market prices…");
  state.marketLoaded = true;
  const rows = d.rows.filter((r) => !r.error);
  const spark = (v) => {
    if (!v || v.length < 2) return "";
    const mn = Math.min(...v), mx = Math.max(...v), w = 110, h = 28;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(h - (x - mn) / ((mx - mn) || 1) * h).toFixed(1)}`).join(" ");
    return `<svg width="${w}" height="${h}"><polyline fill="none" stroke="${v[v.length - 1] >= v[0] ? UP : DOWN}" stroke-width="2" points="${pts}"/></svg>`;
  };
  $("#mk-table").innerHTML = table([
    { label: "Name", key: "name", left: true },
    { label: "Price (₹)", key: "close", fmt: (v) => Number(v).toLocaleString("en-IN") },
    { label: "Today", key: "chg_1d", fmt: (v) => signed(v, 2), color: true },
    { label: "1 month", key: "chg_1m", fmt: (v) => signed(v), color: true },
    { label: "1 year", key: "chg_1y", fmt: (v) => signed(v), color: true },
    { label: "Last 3 months", key: "spark", fmt: spark },
  ], rows, { rowClass: () => "clickable" });
  $$("#mk-table tbody tr").forEach((tr, i) => tr.addEventListener("click", async () => {
    renderDatasets("YF:" + rows[i].symbol);
    showTab("backtest");
    if (await datasetChanged()) runBacktest();
  }));
}

// ------------------------------------------------------------------ strategy settings
function renderParams() {
  const key = $("#bt-strategy").value;
  const s = state.strategies.find((x) => x.key === key);
  $("#rule-builder").classList.toggle("hidden", key !== "custom");
  $("#bt-desc").textContent = s ? s.description : "Write your own buy and sell rules below.";
  $("#bt-params").innerHTML = !s ? "" : s.params.filter((p) => p.name !== "retrain_every").map((p) => {
    if (p.kind === "choice") {
      return `<label class="field">${p.label}<select data-param="${p.name}">${p.grid.map((g) =>
        `<option ${g === p.default ? "selected" : ""}>${g}</option>`).join("")}</select></label>`;
    }
    const step = p.kind === "float" ? "0.01" : "1";
    return `<label class="field">${p.label}<input type="number" step="${step}" data-param="${p.name}" value="${p.default}"></label>`;
  }).join("");
}
function collectParams() {
  const out = {};
  $$("#bt-params [data-param]").forEach((el) => {
    out[el.dataset.param] = el.tagName === "SELECT" ? el.value : Number(el.value);
  });
  return out;
}

const OPERANDS = [["price", "Price"], ["sma", "Moving average (SMA)"], ["ema", "Moving average (EMA)"],
  ["rsi", "RSI"], ["momentum", "Change over N days %"], ["value", "Number"]];
const OPS = [[">", "is above"], ["<", "is below"], ["crosses_above", "crosses above"], ["crosses_below", "crosses below"]];
const hasN = (t) => !["price", "value"].includes(t);

function operandHTML(side, spec) {
  const t = spec.type;
  return `<span class="opnd" data-side="${side}">
    <select class="ot">${OPERANDS.map(([v, l]) => `<option value="${v}" ${v === t ? "selected" : ""}>${l}</option>`).join("")}</select>
    <input type="number" class="on" value="${t === "value" ? (spec.value ?? 0) : (spec.n ?? 14)}" ${t === "price" ? 'style="display:none"' : ""}>
  </span>`;
}
function addCond(which, cond) {
  cond = cond || { left: { type: "price" }, op: ">", right: { type: "sma", n: 50 } };
  const div = document.createElement("div");
  div.className = "cond";
  div.innerHTML = operandHTML("l", cond.left)
    + `<select class="op">${OPS.map(([v, l]) => `<option value="${v}" ${v === cond.op ? "selected" : ""}>${l}</option>`).join("")}</select>`
    + operandHTML("r", cond.right) + `<button class="x" title="Remove">✕</button>`;
  div.querySelector(".x").onclick = () => div.remove();
  div.querySelectorAll(".ot").forEach((sel) => sel.addEventListener("change", () => {
    const inp = sel.nextElementSibling;
    inp.style.display = sel.value === "price" ? "none" : "";
    if (sel.value === "value") inp.value = 50;
  }));
  $("#rb-" + which).appendChild(div);
}
function readOperand(span) {
  const t = span.querySelector(".ot").value;
  const n = Number(span.querySelector(".on").value);
  if (t === "value") return { type: "value", value: n };
  return hasN(t) ? { type: t, n } : { type: t };
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
  }[name];
  P.entry.forEach((c) => addCond("entry", c));
  P.exit.forEach((c) => addCond("exit", c));
}

// ------------------------------------------------------------------ backtest
async function runBacktest() {
  const key = $("#bt-strategy").value;
  const body = { ...base(), key };
  if (key === "custom") body.rules = collectRules(); else body.params = collectParams();
  const d = await api("/api/backtest", body, "Running backtest…");
  const m = d.result.metrics, b = d.benchmark.metrics;
  const dates = d.result.dates;
  const startMoney = body.capital;
  const beat = m.total_return > b.total_return;

  $("#bt-summary").innerHTML = `${rupees(startMoney)} became <b class="${cls(m.total_return)}">${rupees(m.final_equity)}</b> with this strategy,
    after ${rupees(m.costs_paid)} in costs. Just buying and holding would have given <b>${rupees(b.final_equity)}</b>
    — the strategy did <b class="${beat ? "pos" : "neg"}">${beat ? "better" : "worse"}</b>.`;

  $("#bt-kpis").innerHTML = [
    kpi("Total return", signed(m.total_return), `Buy & hold: ${signed(b.total_return)}`, cls(m.total_return)),
    kpi("Return per year", signed(m.cagr), `Buy & hold: ${signed(b.cagr)}`, cls(m.cagr)),
    kpi("Sharpe ratio", fmt(m.sharpe), `Buy & hold: ${fmt(b.sharpe)}`, m.sharpe >= b.sharpe ? "pos" : "neg"),
    kpi("Biggest fall", pct(m.max_drawdown), `Buy & hold: ${pct(b.max_drawdown)}`, "neg"),
    kpi("Winning trades", pct(m.win_rate, 0), `of ${m.num_trades} trades`),
  ].join("");

  const p = d.price;
  const traces = [{ x: dates, y: p.close, name: "Price", line: { color: "#374151", width: 1.4 }, yaxis: "y" }];
  Object.entries(d.overlays.lines || {}).forEach(([name, vals], i) => traces.push({
    x: dates, y: vals, name, line: { width: 1.6, color: COLORS[(i + 1) % COLORS.length] }, yaxis: "y",
  }));
  const tr = d.result.trades;
  traces.push({
    x: tr.map((t) => t.entry_date), y: tr.map((t) => t.entry_price), mode: "markers", name: "Buy",
    marker: { symbol: "triangle-up", size: 12, color: UP }, yaxis: "y",
  });
  const closed = tr.filter((t) => !t.open);
  traces.push({
    x: closed.map((t) => t.exit_date), y: closed.map((t) => t.exit_price), mode: "markers", name: "Sell",
    marker: { symbol: "triangle-down", size: 12, color: DOWN }, yaxis: "y",
  });
  const layout = { yaxis: { title: "Price (₹)" } };
  const panel = d.overlays.panel;
  if (panel) {
    traces.push({ x: dates, y: panel.values, name: panel.name, line: { color: COLORS[2], width: 1.3 }, yaxis: "y2" });
    (panel.levels || []).forEach((lv) => traces.push({
      x: [dates[0], dates[dates.length - 1]], y: [lv, lv], mode: "lines", showlegend: false,
      line: { dash: "dot", color: BH_COLOR, width: 1 }, yaxis: "y2", hoverinfo: "skip",
    }));
    layout.yaxis = { domain: [0.32, 1], title: "Price (₹)" };
    layout.yaxis2 = { domain: [0, 0.24], gridcolor: "#eef0f3", title: panel.name.split(" ")[0] };
  }
  plot("bt-price", traces, layout);

  plot("bt-equity", [
    { x: dates, y: d.result.equity, name: "This strategy", line: { color: COLORS[0], width: 2.5 } },
    { x: dates, y: d.benchmark.equity, name: "Buy & hold", line: { color: BH_COLOR, width: 2, dash: "dash" } },
  ], { yaxis: { title: "Value (₹)", tickformat: ",.0f" } });

  $("#bt-trades").innerHTML = tr.length ? table([
    { label: "Bought", key: "entry_date" }, { label: "Sold", key: "exit_date", fmt: (v, r) => r.open ? "still open" : v },
    { label: "Buy price", key: "entry_price", fmt: (v) => fmt(v) }, { label: "Sell price", key: "exit_price", fmt: (v) => fmt(v) },
    { label: "Shares", key: "shares" },
    { label: "Profit (₹)", key: "pnl", fmt: (v) => Math.round(v).toLocaleString("en-IN"), color: true },
    { label: "Return", key: "return_pct", fmt: (v) => signed(v, 2), color: true },
  ], tr) : `<p class="muted">No trades in this period.</p>`;
}

// ------------------------------------------------------------------ compare (+ costs and market types)
async function runCompare() {
  const specs = checkedSpecs($("#cmp-list"));
  if (!specs.length) return toast("Pick at least one strategy");
  const d = await api("/api/compare", { ...base(), strategies: specs }, "Comparing strategies…");
  $("#cmp-table").innerHTML = table([
    { label: "#", key: "rank" }, { label: "Strategy", key: "name", left: true },
    { label: "Sharpe", key: "sharpe", fmt: (v) => fmt(v) },
    { label: "Total return", key: "total_return", fmt: (v) => signed(v), color: true },
    { label: "Per year", key: "cagr", fmt: (v) => signed(v), color: true },
    { label: "Biggest fall", key: "max_drawdown", fmt: (v) => pct(v) },
    { label: "Winning trades", key: "win_rate", fmt: (v) => pct(v, 0) },
    { label: "Trades", key: "num_trades" },
  ], d.leaderboard, { rowClass: (r) => r.name === "Buy & Hold" ? "bench" : r.rank === 1 ? "highlight" : "" });

  const names = Object.keys(d.series);
  const color = (n, i) => n === "Buy & Hold" ? BH_COLOR : COLORS[i % COLORS.length];
  plot("cmp-equity", names.map((n, i) => ({
    x: d.series[n].dates, y: d.series[n].equity, name: n,
    line: { color: color(n, i), width: 2, dash: n === "Buy & Hold" ? "dash" : "solid" },
  })), { yaxis: { title: "Value (₹)", tickformat: ",.0f" } });

  const cs = await api("/api/costs", { ...base(), strategies: specs }, "Checking the effect of costs…");
  plot("cs-return", [
    ...cs.strategies.map((s, i) => ({ x: cs.levels, y: s.rows.map((r) => r.total_return), name: s.name, mode: "lines+markers", line: { color: COLORS[i % COLORS.length], width: 2 } })),
    { x: cs.levels, y: cs.buy_and_hold.map((r) => r.total_return), name: "Buy & Hold", mode: "lines", line: { color: BH_COLOR, dash: "dash", width: 2 } },
  ], { xaxis: { title: "Cost per trade (bps, 100 = 1%)" }, yaxis: { title: "Total return %" } });
  $("#cs-table").innerHTML = table([
    { label: "Strategy", key: "name", left: true },
    { label: "Trades", get: (s) => s.rows[0].trades },
    { label: "Return with no costs", get: (s) => s.rows[0].total_return, fmt: (v) => signed(v), color: true },
    { label: "Return lost at 0.1% cost", key: "return_lost_at_10bps", fmt: (v) => fmt(v, 1) + " points" },
    { label: "Stops making money at", key: "break_even_bps", fmt: (v) => v === null ? "over 1% per trade" : (v / 100).toFixed(2) + "% per trade" },
  ], cs.strategies);

  const rg = await api("/api/regimes", { ...base(), strategies: specs }, "Checking bull, bear and sideways markets…");
  const order = ["Bull", "Sideways", "Bear"].filter((k) => rg.performance.some((p) => p.regime === k));
  const perf = order.map((k) => rg.performance.find((p) => p.regime === k));
  plot("rg-bars", rg.strategies.map((s, i) => ({
    type: "bar", name: s, x: perf.map((p) => p.regime), y: perf.map((p) => p[s] ? p[s].ann_return : null),
    marker: { color: s === "Buy & Hold" ? BH_COLOR : COLORS[i % COLORS.length] },
  })), { barmode: "group", yaxis: { title: "Return per year %" }, xaxis: { tickangle: 0 }, hovermode: "closest" });
}

// ------------------------------------------------------------------ validate (train/test + walk-forward)
const VERDICT_TEXT = {
  Robust: "It kept working on new data, so the result looks real.",
  Degraded: "It still made money on new data, but less than half as well as in training.",
  Overfit: "It worked in training but lost money on new data. The settings were fitted to the past.",
  "No Edge": "It didn't work well even on the training data.",
};
async function runValidate() {
  const key = $("#val-strategy").value;
  const d = await api("/api/validate", { ...base(), key, train_ratio: +$("#val-ratio").value }, "Test 1: tuning on old data, testing on new data…");
  const is = d.in_sample.metrics, os = d.out_of_sample.metrics;
  const params = Object.entries(d.best_params).map(([k, v]) => `${k} ${v}`).join(", ");
  $("#val-verdict").innerHTML = verdictBox(d.verdict, `${VERDICT_TEXT[d.verdict]} Best settings found: ${esc(params)}.`);
  $("#val-kpis").innerHTML = [
    kpi("Training return", signed(is.total_return), `${d.train_period[0]} to ${d.train_period[1]}`, cls(is.total_return)),
    kpi("Test return", signed(os.total_return), `${d.test_period[0]} to ${d.test_period[1]}`, cls(os.total_return)),
    kpi("Training Sharpe", fmt(is.sharpe), "return for the risk taken"),
    kpi("Test Sharpe", fmt(os.sharpe), "the number that matters", os.sharpe > 0 ? "pos" : "neg"),
  ].join("");
  const scale = d.in_sample.equity[d.in_sample.equity.length - 1] / (+$("#capital").value || 100000);
  const osD = d.out_of_sample.dates;
  plot("val-equity", [
    { x: d.in_sample.dates, y: d.in_sample.equity, name: "Training period", line: { color: COLORS[5], width: 2.5 } },
    { x: osD, y: d.out_of_sample.equity.map((v) => v * scale), name: "Test period (new data)", line: { color: COLORS[1], width: 2.5 } },
  ], {
    yaxis: { title: "Value (₹)", tickformat: ",.0f" },
    shapes: [{ type: "rect", xref: "x", yref: "paper", x0: osD[0], x1: osD[osD.length - 1], y0: 0, y1: 1, fillcolor: "rgba(13,148,136,.07)", line: { width: 0 } }],
  });

  const w = await api("/api/walkforward", { ...base(), key, train_days: +$("#wf-train").value, test_days: +$("#wf-test").value },
    "Test 2: repeating across many periods…");
  const s = w.summary, b = w.benchmark.metrics;
  $("#wf-verdict").innerHTML = verdictBox(s.verdict,
    `${VERDICT_TEXT[s.verdict]} It made money in ${fmt(s.pct_windows_profitable, 0)}% of the ${s.n_windows} test periods.`);
  $("#wf-kpis").innerHTML = [
    kpi("Return on new data", signed(s.oos_total_return), `Buy & hold: ${signed(b.total_return)}`, cls(s.oos_total_return)),
    kpi("Sharpe on new data", fmt(s.oos_sharpe), `Buy & hold: ${fmt(b.sharpe)}`, s.oos_sharpe >= b.sharpe ? "pos" : "neg"),
    kpi("Biggest fall", pct(s.oos_max_drawdown), `Buy & hold: ${pct(b.max_drawdown)}`, "neg"),
    kpi("Periods with profit", pct(s.pct_windows_profitable, 0), `of ${s.n_windows} periods`),
  ].join("");
  const lbl = w.windows.map((x) => x.test[0].slice(0, 7));
  plot("wf-bars", [
    { type: "bar", x: lbl, y: w.windows.map((x) => x.is_sharpe), name: "Training", marker: { color: COLORS[5] } },
    { type: "bar", x: lbl, y: w.windows.map((x) => x.oos_sharpe), name: "Next period", marker: { color: COLORS[1] } },
  ], { barmode: "group", xaxis: { type: "category", title: "Test period starting" }, yaxis: { title: "Sharpe ratio" }, hovermode: "closest" });
}

// ------------------------------------------------------------------ ML
async function runML() {
  const model = $("#ml-model").value;
  const d = await api("/api/ml", { ...base(), model }, model === "random_forest" ? "Training the model (about 10 seconds)…" : "Training the model…");
  const m = d.backtest.metrics, b = d.benchmark.metrics;
  const edge = d.accuracy - d.baseline_accuracy;
  const [verdict, text] = edge > 1
    ? ["Robust", `It guessed the direction right ${pct(d.accuracy, 1)} of the time, better than always guessing "up" (${pct(d.baseline_accuracy, 1)}).`]
    : edge > -0.5
      ? ["Degraded", `It guessed right ${pct(d.accuracy, 1)} of the time, about the same as always guessing "up" (${pct(d.baseline_accuracy, 1)}). Daily moves are mostly random, so this is expected.`]
      : ["Overfit", `It guessed right only ${pct(d.accuracy, 1)} of the time, worse than always guessing "up" (${pct(d.baseline_accuracy, 1)}).`];
  $("#ml-verdict").innerHTML = verdictBox(verdict, text);
  $("#ml-kpis").innerHTML = [
    kpi("Correct guesses", pct(d.accuracy, 1), `always "up": ${pct(d.baseline_accuracy, 1)}`, edge > 0 ? "pos" : "neg"),
    kpi("Strategy return", signed(m.total_return), `Buy & hold: ${signed(b.total_return)}`, cls(m.total_return)),
    kpi("Sharpe ratio", fmt(m.sharpe), `Buy & hold: ${fmt(b.sharpe)}`, m.sharpe >= b.sharpe ? "pos" : "neg"),
    kpi("Biggest fall", pct(m.max_drawdown), `Buy & hold: ${pct(b.max_drawdown)}`, "neg"),
  ].join("");
  plot("ml-equity", [
    { x: d.backtest.dates, y: d.backtest.equity, name: "ML strategy", line: { color: COLORS[0], width: 2.5 } },
    { x: d.backtest.dates, y: d.benchmark.equity, name: "Buy & hold", line: { color: BH_COLOR, width: 2, dash: "dash" } },
  ], { yaxis: { title: "Value (₹)", tickformat: ",.0f" } });
  const NAMES = { ret_1: "1-day change", ret_5: "1-week change", ret_10: "2-week change", ret_20: "1-month change",
    rsi_14: "RSI", dist_sma20: "vs 20-day average", dist_sma50: "vs 50-day average", dist_sma200: "vs 200-day average",
    vol_20: "Volatility", vol_ratio: "Volatility change", volume_z: "Unusual volume", range_pct: "Daily range" };
  const imp = Object.entries(d.feature_importance).slice(0, 8).reverse();
  plot("ml-imp", [{ type: "bar", orientation: "h", x: imp.map((x) => x[1] * 100), y: imp.map((x) => NAMES[x[0]] || x[0]), marker: { color: COLORS[0] } }],
    { margin: { l: 160 }, xaxis: { title: "Importance (%)" }, hovermode: "closest" });
}

// ------------------------------------------------------------------ report
function reportBody() {
  return { ...base(), strategies: checkedSpecs($("#rp-list")), validation: true };
}
async function runReport() {
  const body = reportBody();
  if (!body.strategies.length) return toast("Pick at least one strategy");
  const r = await api("/api/report", body, "Writing the report…");
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const lb = table([
    { label: "#", key: "rank" }, { label: "Strategy", key: "name", left: true }, { label: "Sharpe", key: "sharpe", fmt: (v) => fmt(v) },
    { label: "Total return", key: "total_return", fmt: (v) => signed(v), color: true },
    { label: "Biggest fall", key: "max_drawdown", fmt: (v) => pct(v) },
    { label: "Winning trades", key: "win_rate", fmt: (v) => pct(v, 0) }, { label: "Trades", key: "num_trades" },
  ], r.leaderboard, { rowClass: (x) => x.name === "Buy & Hold" ? "bench" : x.rank === 1 ? "highlight" : "" });
  const sections = r.sections.map((s) => {
    const v = s.validation;
    const vline = v && v.is_sharpe !== undefined ? verdictBox(v.verdict,
      `Training Sharpe ${fmt(v.is_sharpe)}, test Sharpe ${fmt(v.oos_sharpe)}.`) : "";
    const list = (xs) => xs.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>None</li>";
    return `<div class="card"><h2>${esc(s.name)}</h2>${vline}
      <div class="sw"><div class="good"><h3>Strengths</h3><ul>${list(s.strengths)}</ul></div>
      <div class="bad"><h3>Weaknesses</h3><ul>${list(s.weaknesses)}</ul></div></div></div>`;
  }).join("");
  $("#rp-body").innerHTML = `
    <div class="card"><h2>Summary: ${esc($("#dataset").selectedOptions[0]?.textContent || r.dataset)}</h2>
      <p class="muted">${r.period[0]} to ${r.period[1]} · starting money ${rupees(r.capital)} · costs ${r.costs.commission_bps + r.costs.slippage_bps} bps per trade</p>
      <ul>${r.summary.map((s) => `<li>${md(s)}</li>`).join("")}</ul></div>
    <div class="card"><h2>Ranking</h2><div class="table-wrap">${lb}</div></div>
    ${sections}
    <div class="card"><h2>How the test was done</h2><ul>${r.methodology.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>`;
}
async function downloadReport() {
  const body = reportBody();
  if (!body.strategies.length) return toast("Pick at least one strategy");
  loading(true, "Writing the report…");
  try {
    const r = await fetch("/api/report.md", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json()).detail);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await r.blob());
    a.download = "alphatrial_report.md";
    a.click();
  } catch (e) { toast("Something went wrong: " + e.message); } finally { loading(false); }
}

init();

/* Shared code for index.html, browse.html and trends.html.
   Loads data/history.csv + data/status.json in the browser and does all the
   calculations here. No libraries; charts are plain SVG. */
const App = (() => {
  const NUMERIC = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precipitation",
    "pressure_msl", "us_aqi", "pm2_5", "pm10", "ozone"];
  const LABEL = {
    temperature_2m: "Temperature", relative_humidity_2m: "Humidity", wind_speed_10m: "Wind speed",
    precipitation: "Precipitation", pressure_msl: "Pressure", us_aqi: "US AQI",
    pm2_5: "PM2.5", pm10: "PM10", ozone: "Ozone",
  };
  const UNIT = {
    temperature_2m: "°C", relative_humidity_2m: "%", wind_speed_10m: "km/h", precipitation: "mm",
    pressure_msl: "hPa", us_aqi: "", pm2_5: "µg/m³", pm10: "µg/m³", ozone: "µg/m³",
  };
  const MOVE_LIMIT = 10;
  const PALETTE = ["#1769aa", "#e6550d", "#2ca02c", "#9467bd", "#d62728", "#8c564b",
    "#e377c2", "#17becf", "#b8860b", "#4b5563", "#0f766e", "#c026d3"];

  // ------------------------------------------------------------ utilities
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (v === "" || v == null || isNaN(Number(v)) ? null : Number(v));

  function fmt(v, digits = 1) {
    if (v == null || isNaN(v)) return "–";
    return Number(v.toFixed(digits)).toLocaleString("en-US", { maximumFractionDigits: digits });
  }
  const withUnit = (col, v, d = 1) => (v == null ? "–" : fmt(v, d) + (UNIT[col] ? " " + UNIT[col] : ""));
  const signed = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v), d);

  function parseCSV(text) {
    const rows = []; let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); cell = ""; if (row.length > 1 || row[0] !== "") rows.push(row); row = [];
      } else cell += c;
    }
    if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
    const head = rows.shift() || [];
    return rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
  }

  // ------------------------------------------------------------ data
  async function load() {
    let offline = false;
    const get = async (url) => {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(url + " -> HTTP " + res.status);
      return res;
    };
    const [hRes, sRes] = await Promise.all([get("data/history.csv"), get("data/status.json")]);
    const rows = parseCSV(await hRes.text());
    for (const r of rows) for (const c of NUMERIC) r[c] = num(r[c]);
    const status = await sRes.json();
    // The service worker answers from its cache when the network is down.
    offline = !navigator.onLine;
    return { rows, status, offline };
  }

  const dates = (rows) => [...new Set(rows.map((r) => r.date))].sort();
  function splitLastTwo(rows) {
    const d = dates(rows);
    if (!d.length) return { prev: [], latest: [], prevDate: null, latestDate: null };
    return {
      latest: rows.filter((r) => r.date === d[d.length - 1]),
      prev: d.length > 1 ? rows.filter((r) => r.date === d[d.length - 2]) : [],
      latestDate: d[d.length - 1], prevDate: d.length > 1 ? d[d.length - 2] : null,
    };
  }

  // The move rule (same as scripts/tracker.py compute_moves):
  // score = |new - old| / population sd of that column across the latest day.
  function computeMoves(prev, latest, limit = MOVE_LIMIT) {
    const P = new Map(prev.map((r) => [r.item_id, r])), C = new Map(latest.map((r) => [r.item_id, r]));
    const sd = {};
    for (const col of NUMERIC) {
      const v = latest.map((r) => r[col]).filter((x) => x != null);
      if (v.length < 2) { sd[col] = 1; continue; }
      const m = v.reduce((a, b) => a + b, 0) / v.length;
      const s = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length);
      sd[col] = s > 0 ? s : 1;
    }
    const moves = [];
    for (const id of [...C.keys()].filter((k) => P.has(k)).sort()) {
      for (const col of NUMERIC) {
        const o = P.get(id)[col], n = C.get(id)[col];
        if (o == null || n == null) continue;
        moves.push({ item_id: id, item: C.get(id).item, column: col, old: o, new: n, change: n - o, score: Math.abs(n - o) / sd[col] });
      }
    }
    moves.sort((a, b) => b.score - a.score || (a.item_id < b.item_id ? -1 : a.item_id > b.item_id ? 1 : 0) || (a.column < b.column ? -1 : a.column > b.column ? 1 : 0));
    return {
      moves: moves.slice(0, limit),
      appeared: prev.length ? [...C.keys()].filter((k) => !P.has(k)).sort() : [],
      gone: prev.length ? [...P.keys()].filter((k) => !C.has(k)).sort() : [],
    };
  }

  function aqiBand(v) {
    if (v == null) return "No data";
    if (v <= 50) return "Good";
    if (v <= 100) return "Moderate";
    if (v <= 150) return "Unhealthy for sensitive groups";
    if (v <= 200) return "Unhealthy";
    if (v <= 300) return "Very unhealthy";
    return "Hazardous";
  }

  // ------------------------------------------------------------ page chrome
  function nav(active) {
    const links = [["index.html", "Today"], ["browse.html", "Browse"], ["trends.html", "Trends"]];
    const el = document.createElement("nav");
    el.className = "top";
    el.innerHTML = `<div class="wrap"><a class="brand" href="index.html">☁ Nimbus 2000</a>` +
      links.map(([h, t]) => `<a class="link" href="${h}"${h === active ? ' aria-current="page"' : ""}>${t}</a>`).join("") +
      `<span class="spacer"></span><span class="net" id="net"></span></div>`;
    document.body.prepend(el);
    const net = () => { $("#net").textContent = navigator.onLine ? "" : "Offline: showing last data"; };
    addEventListener("online", net); addEventListener("offline", net); net();
  }

  function footer() {
    const f = document.createElement("footer");
    f.innerHTML = `Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0).`;
    $(".wrap").appendChild(f);
  }

  function registerSW() {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  async function boot(active, render) {
    nav(active); registerSW();
    const main = $("main");
    try {
      const data = await load();
      if (!data.rows.length) { main.insertAdjacentHTML("beforeend", `<p class="muted">No data yet. Run the daily workflow first.</p>`); }
      else render(data, main);
    } catch (e) {
      main.insertAdjacentHTML("beforeend", `<p class="err">Could not load data: ${esc(e.message)}</p>`);
    }
    footer();
  }

  // ------------------------------------------------------------ charts (SVG)
  const W = 640, H = 300, M = { l: 52, r: 14, t: 12, b: 34 };

  function niceTicks(lo, hi, n = 5) {
    if (!isFinite(lo) || !isFinite(hi)) return [0, 1];
    if (lo === hi) { const d = Math.abs(lo) * 0.1 || 1; lo -= d; hi += d; }
    const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0)), r = step0 / mag;
    const step = (r >= 5 ? 10 : r >= 2 ? 5 : r >= 1 ? 2 : 1) * mag;
    const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, t = [];
    for (let v = a; v <= b + step / 2; v += step) t.push(Number(v.toFixed(10)));
    return t;
  }

  function axes(ticks, y, innerW) {
    return ticks.map((t) => `<line class="grid" x1="${M.l}" x2="${M.l + innerW}" y1="${y(t)}" y2="${y(t)}"/><text x="${M.l - 6}" y="${y(t) + 4}" text-anchor="end">${esc(fmt(t, 2))}</text>`).join("");
  }

  function setChart(el, svg, label) {
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${svg}</svg>`;
  }

  /* series: [{name, color, points:[{x: index, y: number|null}]}], labels: x labels */
  function lineChart(el, { labels, series, unit = "", label = "Line chart" }) {
    const iw = W - M.l - M.r, ih = H - M.t - M.b;
    const ys = series.flatMap((s) => s.points.map((p) => p.y).filter((v) => v != null));
    if (!ys.length) { el.innerHTML = `<p class="muted">No data to show.</p>`; return; }
    const ticks = niceTicks(Math.min(...ys), Math.max(...ys));
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const x = (i) => M.l + (labels.length < 2 ? iw / 2 : (i / (labels.length - 1)) * iw);
    const y = (v) => M.t + ih - ((v - lo) / (hi - lo || 1)) * ih;
    let svg = axes(ticks, y, iw) + `<line class="axis" x1="${M.l}" x2="${M.l + iw}" y1="${M.t + ih}" y2="${M.t + ih}"/>`;
    const step = Math.max(1, Math.ceil(labels.length / 7));
    labels.forEach((l, i) => { if (i % step === 0 || i === labels.length - 1) svg += `<text x="${x(i)}" y="${H - 12}" text-anchor="middle">${esc(l.slice(5))}</text>`; });
    for (const s of series) {
      const seg = []; let cur = [];
      s.points.forEach((p) => { if (p.y == null) { if (cur.length) seg.push(cur); cur = []; } else cur.push(p); });
      if (cur.length) seg.push(cur);
      for (const g of seg) if (g.length > 1) svg += `<polyline fill="none" stroke="${s.color}" stroke-width="2" points="${g.map((p) => x(p.x) + "," + y(p.y)).join(" ")}"/>`;
      for (const p of s.points) if (p.y != null) svg += `<circle cx="${x(p.x)}" cy="${y(p.y)}" r="3.2" fill="${s.color}"><title>${esc(s.name)}, ${esc(labels[p.x])}: ${esc(fmt(p.y, 2))} ${esc(unit)}</title></circle>`;
    }
    if (unit) svg += `<text x="${M.l}" y="${M.t + 2}" dy="-2" text-anchor="start" style="font-size:10px">${esc(unit)}</text>`;
    setChart(el, svg, label);
  }

  /* bars: [{label, value, color?}] ; horizontal bars so long names fit */
  function barChart(el, { bars, unit = "", label = "Bar chart", digits = 1 }) {
    const items = bars.filter((b) => b.value != null);
    if (!items.length) { el.innerHTML = `<p class="muted">No data to show.</p>`; return; }
    const rowH = 24, h = items.length * rowH + 30, left = 120, right = 70, iw = W - left - right;
    const vals = items.map((b) => b.value), lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const x = (v) => left + ((v - lo) / (hi - lo || 1)) * iw, zero = x(0);
    let svg = `<line class="axis" x1="${zero}" x2="${zero}" y1="4" y2="${h - 22}"/>`;
    items.forEach((b, i) => {
      const yy = 6 + i * rowH, x0 = Math.min(zero, x(b.value)), w = Math.max(1.5, Math.abs(x(b.value) - zero));
      svg += `<text x="${left - 8}" y="${yy + 13}" text-anchor="end">${esc(b.label)}</text>` +
        `<rect x="${x0}" y="${yy}" width="${w}" height="${rowH - 7}" rx="3" fill="${b.color || PALETTE[0]}"><title>${esc(b.label)}: ${esc(fmt(b.value, digits))} ${esc(unit)}</title></rect>` +
        `<text class="bar-label" x="${b.value >= 0 ? x0 + w + 5 : zero + 5}" y="${yy + 13}" text-anchor="start">${esc(fmt(b.value, digits))}</text>`;
    });
    if (unit) svg += `<text x="${left}" y="${h - 6}">${esc(unit)}</text>`;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(label)}">${svg}</svg>`;
  }

  /* points: [{x, y, label}] */
  function scatterChart(el, { points, xLabel, yLabel, label = "Scatter chart" }) {
    const pts = points.filter((p) => p.x != null && p.y != null);
    if (!pts.length) { el.innerHTML = `<p class="muted">No data to show.</p>`; return; }
    const iw = W - M.l - M.r, ih = H - M.t - M.b;
    const ty = niceTicks(Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y)));
    const tx = niceTicks(Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)));
    const x = (v) => M.l + ((v - tx[0]) / (tx[tx.length - 1] - tx[0] || 1)) * iw;
    const y = (v) => M.t + ih - ((v - ty[0]) / (ty[ty.length - 1] - ty[0] || 1)) * ih;
    let svg = axes(ty, y, iw) + `<line class="axis" x1="${M.l}" x2="${M.l + iw}" y1="${M.t + ih}" y2="${M.t + ih}"/>`;
    tx.forEach((t) => { svg += `<text x="${x(t)}" y="${H - 18}" text-anchor="middle">${esc(fmt(t, 2))}</text>`; });
    svg += `<text x="${M.l + iw / 2}" y="${H - 3}" text-anchor="middle">${esc(xLabel)}</text>` +
      `<text x="${M.l}" y="${M.t}" dy="-2" style="font-size:10px">${esc(yLabel)}</text>`;
    for (const p of pts) svg += `<circle cx="${x(p.x)}" cy="${y(p.y)}" r="4" fill="${PALETTE[0]}" fill-opacity=".55"><title>${esc(p.label)}: ${esc(fmt(p.x, 2))}, ${esc(fmt(p.y, 2))}</title></circle>`;
    setChart(el, svg, label);
  }

  return { NUMERIC, LABEL, UNIT, PALETTE, MOVE_LIMIT, $, esc, num, fmt, withUnit, signed, parseCSV, load, dates,
    splitLastTwo, computeMoves, aqiBand, boot, lineChart, barChart, scatterChart };
})();
if (typeof module !== "undefined") module.exports = App;

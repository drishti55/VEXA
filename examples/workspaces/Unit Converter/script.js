// Storage that also works inside a sandboxed preview frame (where localStorage throws).
const store = (() => {
  const mem = {};
  return {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); }
      catch { return key in mem ? mem[key] : fallback; }
    },
    set(key, value) { mem[key] = value; try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* sandboxed */ } },
  };
})();
const $ = (sel) => document.querySelector(sel);
function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  Object.entries(props).forEach(([k, v]) => {
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (k in n) n[k] = v;
    else n.setAttribute(k, v);
  });
  children.flat().forEach(c => n.append(c instanceof Node ? c : document.createTextNode(String(c))));
  return n;
}
const today = () => new Date().toISOString().slice(0, 10);
function beep(freq = 880, ms = 400) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = freq; o.connect(g); g.connect(ctx.destination);
    g.gain.setValueAtTime(0.2, ctx.currentTime); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + ms / 1000);
    o.start(); o.stop(ctx.currentTime + ms / 1000);
  } catch { /* audio unavailable */ }
}
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); if (btn) { const t = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => (btn.textContent = t), 1000); } }
  catch { prompt('Copy:', text); }
}

const U = {
  Length: { m: 1, km: 1000, cm: 0.01, mm: 0.001, mi: 1609.344, yd: 0.9144, ft: 0.3048, in: 0.0254 },
  Weight: { kg: 1, g: 0.001, mg: 1e-6, t: 1000, lb: 0.45359237, oz: 0.028349523125 },
  Volume: { L: 1, mL: 0.001, 'm³': 1000, 'gal (US)': 3.785411784, 'cup (US)': 0.2365882365, 'fl oz (US)': 0.0295735295625 },
  Speed: { 'm/s': 1, 'km/h': 1 / 3.6, mph: 0.44704, knot: 0.514444 },
  Time: { s: 1, ms: 0.001, min: 60, h: 3600, day: 86400, week: 604800 },
  Data: { B: 1, KB: 1e3, MB: 1e6, GB: 1e9, TB: 1e12, KiB: 1024, MiB: 1048576, GiB: 1073741824 },
  Temperature: { '°C': 'C', '°F': 'F', K: 'K' },
};
const toC = { C: v => v, F: v => (v - 32) * 5 / 9, K: v => v - 273.15 }, fromC = { C: v => v, F: v => v * 9 / 5 + 32, K: v => v + 273.15 };
function convert(v, cat, a, b) { if (cat === 'Temperature') return fromC[U[cat][b]](toC[U[cat][a]](v)); return v * U[cat][a] / U[cat][b]; }
const nice = n => (Math.abs(n) >= 1e9 || (Math.abs(n) < 1e-4 && n !== 0) ? n.toExponential(4) : +n.toPrecision(8)).toString();
$('#cat').replaceChildren(...Object.keys(U).map(c => el('option', {}, c)));
function units() { const keys = Object.keys(U[$('#cat').value]); [$('#fu'), $('#tu')].forEach((s, i) => { s.replaceChildren(...keys.map(k => el('option', {}, k))); s.value = keys[Math.min(i, keys.length - 1)]; }); run(); }
function run(reverse) {
  const cat = $('#cat').value;
  if (reverse) { $('#from').value = nice(convert(+$('#to').value, cat, $('#tu').value, $('#fu').value)); }
  else { $('#to').value = $('#from').value === '' ? '' : nice(convert(+$('#from').value, cat, $('#fu').value, $('#tu').value)); }
  $('#formula').textContent = `1 ${$('#fu').value} = ${nice(convert(1, cat, $('#fu').value, $('#tu').value))} ${$('#tu').value}`;
  $('#all').replaceChildren(...Object.keys(U[cat]).map(k => el('li', {}, el('span', { class: 'grow' }, k), el('b', {}, nice(convert(+$('#from').value || 0, cat, $('#fu').value, k))))));
}
$('#cat').onchange = units; $('#from').oninput = () => run(); $('#to').oninput = () => run(true); $('#fu').onchange = () => run(); $('#tu').onchange = () => run();
$('#swap').onclick = () => { const a = $('#fu').value; $('#fu').value = $('#tu').value; $('#tu').value = a; run(); };
units();

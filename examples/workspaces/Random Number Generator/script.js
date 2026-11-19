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

function gen() {
  const min = Math.ceil(+$('#min').value), max = Math.floor(+$('#max').value), count = Math.max(1, Math.min(1000, parseInt($('#count').value, 10) || 1));
  if (!Number.isFinite(min) || !Number.isFinite(max) || min > max) return ($('#info').textContent = 'Min must be ≤ max.');
  const span = max - min + 1;
  if ($('#unique').checked && count > span) return ($('#info').textContent = `Only ${span} unique numbers exist in that range.`);
  const out = [], seen = new Set(), rand = () => min + Math.floor((crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32) * span);
  while (out.length < count) { const v = rand(); if ($('#unique').checked) { if (seen.has(v)) continue; seen.add(v); } out.push(v); }
  if ($('#sort').checked) out.sort((a, b) => a - b);
  $('#out').textContent = out.join(', ');
  $('#info').textContent = count > 1 ? `sum ${out.reduce((a, b) => a + b, 0)} · average ${(out.reduce((a, b) => a + b, 0) / count).toFixed(2)}` : `between ${min} and ${max}`;
}
$('#go').onclick = gen; $('#copy').onclick = e => copyText($('#out').textContent, e.target);
gen();

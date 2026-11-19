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

const plans = store.get('planner', {});
const date = $('#date'); date.value = today();
function shift(n) { const d = new Date(date.value); d.setDate(d.getDate() + n); date.value = d.toISOString().slice(0, 10); render(); }
function render() {
  const day = plans[date.value] || {};
  const box = $('#slots'); box.replaceChildren();
  const now = new Date(), isToday = date.value === today();
  for (let h = 6; h <= 22; h++) {
    const label = `${((h + 11) % 12) + 1}:00 ${h < 12 ? 'AM' : 'PM'}`;
    const input = el('input', { class: 'grow', value: day[h] || '', placeholder: '—', oninput: e => { plans[date.value] = { ...(plans[date.value] || {}), [h]: e.target.value }; store.set('planner', plans); } });
    const past = isToday && h < now.getHours(), current = isToday && h === now.getHours();
    const row = el('div', { class: 'row', style: `padding:4px 0;${current ? 'border-left:3px solid var(--accent);padding-left:6px' : ''}${past ? ';opacity:.55' : ''}` },
      el('span', { style: 'width:78px', class: 'muted' }, label), input);
    box.append(row);
  }
}
$('#prev').onclick = () => shift(-1); $('#next').onclick = () => shift(1); date.onchange = render;
$('#clear').onclick = () => { if (confirm('Clear all plans for this day?')) { delete plans[date.value]; store.set('planner', plans); render(); } };
render();

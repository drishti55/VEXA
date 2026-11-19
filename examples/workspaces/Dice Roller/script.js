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

const FACES = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];
let history = store.get('dice.history', []);
function face(v, sides) {
  return sides == 6 ? el('span', { style: 'font-size:72px;line-height:1' }, FACES[v - 1])
    : el('span', { style: 'display:inline-grid;place-items:center;width:64px;height:64px;border:2px solid var(--accent);border-radius:12px;font-size:26px;font-weight:700' }, v);
}
function roll() {
  const n = Math.min(6, Math.max(1, parseInt($('#count').value, 10) || 1)), sides = +$('#sides').value;
  const vals = [...Array(n)].map(() => 1 + Math.floor(Math.random() * sides));
  const box = $('#dice'); box.style.opacity = 0.3;
  setTimeout(() => {
    box.replaceChildren(...vals.map(v => face(v, sides))); box.style.opacity = 1;
    const total = vals.reduce((a, b) => a + b, 0);
    $('#total').textContent = n > 1 ? `Total ${total}` : total;
    history.unshift(`${n}d${sides}: ${vals.join(' + ')} = ${total}`); history = history.slice(0, 20); store.set('dice.history', history); renderHistory();
  }, 180);
}
function renderHistory() { $('#history').replaceChildren(...(history.length ? history.map(h => el('li', {}, h)) : [el('li', { class: 'muted' }, 'No rolls yet.')])); }
$('#roll').onclick = roll; $('#clear').onclick = () => { history = []; store.set('dice.history', history); renderHistory(); };
document.addEventListener('keydown', e => { if (e.key === ' ' && e.target.tagName !== 'INPUT') { e.preventDefault(); roll(); } });
renderHistory();

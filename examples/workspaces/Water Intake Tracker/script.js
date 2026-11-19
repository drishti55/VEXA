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

let goal = store.get('water.goal', 2000);
let log = store.get('water.log', {});
$('#goal').value = goal;
const entries = () => log[today()] || [];
const save = () => { store.set('water.log', log); store.set('water.goal', goal); };
function add(ml) { if (!(ml > 0)) return; log[today()] = [...entries(), { ml, at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }]; save(); render(); }
function render() {
  const total = entries().reduce((s, e) => s + e.ml, 0);
  $('#amount').textContent = `${total} ml`;
  $('#fill').style.height = Math.min(100, 100 * total / goal) + '%';
  $('#left').textContent = total >= goal ? '🎉 Goal reached!' : `${goal - total} ml to go`;
  $('#log').replaceChildren(...entries().slice().reverse().map(e => el('li', {}, el('span', { class: 'grow' }, `${e.ml} ml`), el('span', { class: 'muted' }, e.at))));
}
document.querySelectorAll('[data-ml]').forEach(b => (b.onclick = () => add(+b.dataset.ml)));
$('#addc').onclick = () => { add(parseInt($('#custom').value, 10)); $('#custom').value = ''; };
$('#undo').onclick = () => { log[today()] = entries().slice(0, -1); save(); render(); };
$('#goal').onchange = () => { const g = parseInt($('#goal').value, 10); if (g > 0) { goal = g; save(); render(); } };
render();

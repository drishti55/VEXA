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

let goals = store.get('goal.goals', []);
let done = store.get('goal.done', {}); // date -> [goal]
const save = () => { store.set('goal.goals', goals); store.set('goal.done', done); };
const isPerfect = d => goals.length && goals.every(g => (done[d] || []).includes(g));
function streaks() {
  const days = Object.keys(done).filter(isPerfect).sort();
  let best = 0, run = 0, prev = null;
  days.forEach(d => { run = prev && (new Date(d) - new Date(prev)) === 864e5 ? run + 1 : 1; best = Math.max(best, run); prev = d; });
  let cur = 0; const t = new Date(today());
  for (;;) { const d = t.toISOString().slice(0, 10); if (!isPerfect(d)) break; cur++; t.setDate(t.getDate() - 1); }
  return { cur, best, perfect: days.length };
}
function render() {
  $('#date').textContent = new Date().toDateString();
  const d = done[today()] || [];
  const list = $('#list'); list.replaceChildren();
  if (!goals.length) list.append(el('li', { class: 'muted' }, 'No goals yet.'));
  goals.forEach(g => {
    const cb = el('input', { type: 'checkbox', checked: d.includes(g), onchange: () => toggle(g) });
    list.append(el('li', {}, cb, el('span', { class: 'grow' + (d.includes(g) ? ' done' : '') }, g),
      el('button', { class: 'small ghost', onclick: () => { goals = goals.filter(x => x !== g); save(); render(); } }, '✕')));
  });
  const pct = goals.length ? Math.round(100 * goals.filter(g => d.includes(g)).length / goals.length) : 0;
  $('#pct').textContent = `${pct}% done`; $('#bar').style.width = pct + '%';
  const s = streaks(); $('#streak').textContent = s.cur; $('#best').textContent = s.best; $('#perfect').textContent = s.perfect;
}
function toggle(g) { const d = new Set(done[today()] || []); d.has(g) ? d.delete(g) : d.add(g); done[today()] = [...d]; save(); render(); }
$('#add').onclick = () => { const g = $('#goal').value.trim(); if (g && !goals.includes(g)) { goals.push(g); save(); } $('#goal').value = ''; render(); };
$('#goal').onkeydown = e => e.key === 'Enter' && $('#add').click();
render();

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

let habits = store.get('habit.list', []);
let checks = store.get('habit.checks', {}); // habit -> [date]
const save = () => { store.set('habit.list', habits); store.set('habit.checks', checks); };
const days = [...Array(7)].map((_, i) => { const d = new Date(); d.setDate(d.getDate() - (6 - i)); return d.toISOString().slice(0, 10); });
function streak(h) { const set = new Set(checks[h] || []); let n = 0; const d = new Date(); for (;;) { const k = d.toISOString().slice(0, 10); if (!set.has(k)) break; n++; d.setDate(d.getDate() - 1); } return n; }
function render() {
  const t = $('#grid'); t.replaceChildren();
  t.append(el('tr', {}, el('th', { style: 'text-align:left' }, 'Habit'), ...days.map(d => el('th', { class: 'muted', style: 'font-weight:500;font-size:12px' }, new Date(d).toLocaleDateString(undefined, { weekday: 'short' }))), el('th', {}, '🔥'), el('th')));
  if (!habits.length) t.append(el('tr', {}, el('td', { colSpan: 10, class: 'muted', style: 'padding:10px 0' }, 'No habits yet.')));
  habits.forEach(h => {
    const set = new Set(checks[h] || []);
    t.append(el('tr', { style: 'border-top:1px solid var(--line)' }, el('td', { style: 'padding:8px 0' }, h),
      ...days.map(d => el('td', { class: 'center' }, el('input', { type: 'checkbox', checked: set.has(d), onchange: () => { set.has(d) ? set.delete(d) : set.add(d); checks[h] = [...set]; save(); render(); } }))),
      el('td', { class: 'center' }, streak(h)),
      el('td', {}, el('button', { class: 'small ghost', onclick: () => { if (confirm(`Delete "${h}"?`)) { habits = habits.filter(x => x !== h); delete checks[h]; save(); render(); } } }, '✕'))));
  });
}
$('#add').onclick = () => { const h = $('#habit').value.trim(); if (h && !habits.includes(h)) { habits.push(h); save(); } $('#habit').value = ''; render(); };
$('#habit').onkeydown = e => e.key === 'Enter' && $('#add').click();
render();

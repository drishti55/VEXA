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

let people = store.get('split.people', []);
let expenses = store.get('split.expenses', []);
const save = () => { store.set('split.people', people); store.set('split.expenses', expenses); };
const money = n => n.toFixed(2);
function settle() {
  if (!people.length) return [];
  const total = expenses.reduce((s, e) => s + e.amount, 0), share = total / people.length;
  const bal = people.map(p => ({ p, v: expenses.filter(e => e.payer === p).reduce((s, e) => s + e.amount, 0) - share }));
  const debtors = bal.filter(b => b.v < -0.005).sort((a, b) => a.v - b.v), creditors = bal.filter(b => b.v > 0.005).sort((a, b) => b.v - a.v);
  const out = [];
  let i = 0, j = 0;
  while (i < debtors.length && j < creditors.length) {
    const x = Math.min(-debtors[i].v, creditors[j].v);
    out.push(`${debtors[i].p} pays ${creditors[j].p} ${money(x)}`);
    debtors[i].v += x; creditors[j].v -= x;
    if (debtors[i].v > -0.005) i++; if (creditors[j].v < 0.005) j++;
  }
  return out;
}
function render() {
  const pbox = $('#people'); pbox.replaceChildren(...people.map(p => el('span', { class: 'pill' }, p, ' ', el('a', { href: '#', onclick: e => { e.preventDefault(); if (expenses.some(x => x.payer === p)) return alert(`${p} has expenses; delete them first.`); people = people.filter(x => x !== p); save(); render(); } }, '✕'))));
  $('#payer').replaceChildren(...people.map(p => el('option', { value: p }, p)));
  const list = $('#expenses'); list.replaceChildren();
  expenses.forEach((e, i) => list.append(el('li', {}, el('span', { class: 'grow' }, e.desc, ' ', el('span', { class: 'muted' }, `paid by ${e.payer}`)), el('b', {}, money(e.amount)),
    el('button', { class: 'small ghost', onclick: () => { expenses.splice(i, 1); save(); render(); } }, '✕'))));
  const total = expenses.reduce((s, e) => s + e.amount, 0);
  if (expenses.length) list.append(el('li', {}, el('span', { class: 'grow muted' }, `Total · ${people.length ? money(total / people.length) : '0.00'} each`), el('b', {}, money(total))));
  const s = settle();
  $('#settle').replaceChildren(...(s.length ? s.map(t => el('li', {}, t)) : [el('li', { class: 'muted' }, expenses.length ? 'Everyone is even.' : 'Add people and expenses.')]));
}
$('#addp').onclick = () => { const p = $('#person').value.trim(); if (p && !people.includes(p)) { people.push(p); save(); } $('#person').value = ''; render(); };
$('#person').onkeydown = e => e.key === 'Enter' && $('#addp').click();
$('#adde').onclick = () => {
  const desc = $('#desc').value.trim() || 'Expense', amount = parseFloat($('#amount').value), payer = $('#payer').value;
  if (!payer) return alert('Add at least one person first.');
  if (!(amount > 0)) return alert('Enter a positive amount.');
  expenses.push({ desc, amount, payer }); save(); $('#desc').value = ''; $('#amount').value = ''; render();
};
render();

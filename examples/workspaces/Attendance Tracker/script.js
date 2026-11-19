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

let students = store.get('att.students', []);
let records = store.get('att.records', {}); // date -> { name: true|false }
const date = $('#date'); date.value = today();
function save() { store.set('att.students', students); store.set('att.records', records); }
function rate(name) {
  const days = Object.values(records).filter(r => name in r);
  return days.length ? Math.round(100 * days.filter(r => r[name]).length / days.length) : null;
}
function render() {
  const day = records[date.value] || {};
  const list = $('#list'); list.replaceChildren();
  if (!students.length) list.append(el('li', { class: 'muted' }, 'Add students to start taking attendance.'));
  students.forEach(s => {
    const st = day[s];
    const r = rate(s);
    list.append(el('li', {},
      el('span', { class: 'grow' }, s, ' ', el('span', { class: 'pill' }, r == null ? 'no records' : `${r}% present`)),
      el('button', { class: 'small' + (st === true ? '' : ' ghost'), onclick: () => mark(s, true) }, 'Present'),
      el('button', { class: 'small' + (st === false ? ' danger' : ' ghost'), onclick: () => mark(s, false) }, 'Absent'),
      el('button', { class: 'small ghost', title: 'Remove student', onclick: () => remove(s) }, '✕')));
  });
  const vals = Object.values(day);
  $('#summary').textContent = `${vals.filter(Boolean).length} present · ${vals.filter(v => v === false).length} absent · ${students.length - vals.length} unmarked`;
}
function mark(s, present) { records[date.value] = { ...(records[date.value] || {}), [s]: present }; save(); render(); }
function remove(s) { if (!confirm(`Remove ${s}?`)) return; students = students.filter(x => x !== s); save(); render(); }
$('#add').onclick = () => { const n = $('#name').value.trim(); if (n && !students.includes(n)) { students.push(n); save(); } $('#name').value = ''; render(); };
$('#name').onkeydown = e => e.key === 'Enter' && $('#add').click();
date.onchange = render;
render();

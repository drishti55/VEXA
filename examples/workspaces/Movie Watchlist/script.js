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

let movies = store.get('movies', []);
const save = () => store.set('movies', movies);
function render() {
  const f = $('#filter').value, q = $('#q').value.toLowerCase();
  const shown = movies.filter(m => (f === 'all' || (f === 'done') === m.watched) && m.title.toLowerCase().includes(q));
  $('#count').textContent = `${movies.filter(m => m.watched).length}/${movies.length} watched`;
  const list = $('#list'); list.replaceChildren();
  if (!shown.length) list.append(el('li', { class: 'muted' }, movies.length ? 'No matches.' : 'Your watchlist is empty.'));
  shown.forEach(m => {
    const stars = el('span', {}, ...[1, 2, 3, 4, 5].map(n => el('span', { style: `cursor:pointer;color:${n <= (m.rating || 0) ? 'var(--warn)' : 'var(--line)'}`, title: `${n} star${n > 1 ? 's' : ''}`, onclick: () => { m.rating = n; m.watched = true; save(); render(); } }, '★')));
    list.append(el('li', {}, el('input', { type: 'checkbox', checked: m.watched, onchange: () => { m.watched = !m.watched; save(); render(); } }),
      el('span', { class: 'grow' + (m.watched ? ' done' : '') }, m.title, m.year ? ` (${m.year})` : '', ' ', el('span', { class: 'pill' }, m.genre)), stars,
      el('button', { class: 'small ghost', onclick: () => { movies = movies.filter(x => x !== m); save(); render(); } }, '✕')));
  });
}
$('#add').onclick = () => { const title = $('#title').value.trim(); if (!title) return; movies.unshift({ title, year: $('#year').value, genre: $('#genre').value, watched: false, rating: 0 }); save(); $('#title').value = ''; $('#year').value = ''; render(); };
$('#title').onkeydown = e => e.key === 'Enter' && $('#add').click();
$('#filter').onchange = render; $('#q').oninput = render;
render();

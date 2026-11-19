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

const MOODS = [['😄', 'Great'], ['🙂', 'Good'], ['😐', 'Okay'], ['😕', 'Low'], ['😢', 'Bad']];
let entries = store.get('mood.entries', {}); // date -> {mood, note}
let picked = entries[today()]?.mood ?? null;
function render() {
  $('#moods').replaceChildren(...MOODS.map(([e, l]) => el('button', { class: picked === e ? '' : 'ghost', style: 'font-size:26px;padding:6px 12px', title: l, onclick: () => { picked = e; render(); } }, e)));
  if (entries[today()] && !$('#note').value) $('#note').value = entries[today()].note || '';
  const since = new Date(); since.setDate(since.getDate() - 30);
  const recent = Object.entries(entries).filter(([d]) => new Date(d) >= since);
  $('#counts').replaceChildren(...MOODS.map(([e, l]) => el('div', { class: 'stat' }, el('b', {}, recent.filter(([, v]) => v.mood === e).length), `${e} ${l}`)));
  const list = $('#history'); list.replaceChildren();
  const all = Object.entries(entries).sort((a, b) => b[0].localeCompare(a[0]));
  if (!all.length) list.append(el('li', { class: 'muted' }, 'No entries yet.'));
  all.forEach(([d, v]) => list.append(el('li', {}, el('span', { style: 'font-size:22px' }, v.mood), el('span', { class: 'grow' }, v.note || el('span', { class: 'muted' }, 'no note')), el('span', { class: 'muted' }, d))));
}
$('#save').onclick = () => { if (!picked) return alert('Pick a mood first.'); entries[today()] = { mood: picked, note: $('#note').value.trim() }; store.set('mood.entries', entries); render(); };
render();

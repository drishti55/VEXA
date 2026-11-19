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

const PASSAGES = [
  'The quick brown fox jumps over the lazy dog while the bright sun shines across the quiet green valley.',
  'Programming is the art of telling another human what one wants the computer to do, clearly and precisely.',
  'Small daily improvements over time lead to stunning results that nobody could have predicted at the start.',
  'A good cup of tea, a comfortable chair and an interesting book can turn any rainy afternoon into a pleasure.',
  'Every great developer you know got there by solving problems they were unqualified to solve until they did it.',
];
let passage = '', start = null, timer = null, left = 60, done = false;
let best = store.get('type.best', null);
function reset() {
  clearInterval(timer); start = null; done = false; left = +$('#dur').value;
  passage = Array.from({ length: 4 }, () => PASSAGES[Math.floor(Math.random() * PASSAGES.length)]).join(' ');
  $('#input').value = ''; $('#input').disabled = false; $('#time').textContent = left; $('#wpm').textContent = 0; $('#acc').textContent = '100%';
  $('#best').textContent = best ?? '–'; paint(); $('#input').focus();
}
function paint() {
  const typed = $('#input').value;
  $('#text').replaceChildren(...[...passage].map((ch, i) => el('span', { style: i < typed.length ? (typed[i] === ch ? 'color:var(--ok)' : 'color:var(--bad);text-decoration:underline') : i === typed.length ? 'border-left:2px solid var(--accent)' : 'color:var(--muted)' }, ch)));
}
function stats() {
  const typed = $('#input').value, mins = Math.max((Date.now() - start) / 60000, 1 / 600);
  const correct = [...typed].filter((c, i) => c === passage[i]).length;
  $('#wpm').textContent = Math.round(correct / 5 / mins);
  $('#acc').textContent = typed.length ? Math.round(100 * correct / typed.length) + '%' : '100%';
}
function finish() {
  done = true; clearInterval(timer); $('#input').disabled = true; stats();
  const w = +$('#wpm').textContent; if (!best || w > best) { best = w; store.set('type.best', best); $('#best').textContent = best; }
}
$('#input').oninput = () => {
  if (done) return;
  if (!start) { start = Date.now(); timer = setInterval(() => { left--; $('#time').textContent = left; stats(); if (left <= 0) finish(); }, 1000); }
  paint(); stats();
  if ($('#input').value.length >= passage.length) finish();
};
$('#restart').onclick = reset; $('#dur').onchange = reset;
reset();

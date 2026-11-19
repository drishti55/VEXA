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

let cards = store.get('flash.cards', [
  { front: 'What does HTML stand for?', back: 'HyperText Markup Language', known: false },
  { front: 'Capital of Japan?', back: 'Tokyo', known: false },
  { front: '7 × 8', back: '56', known: false },
]);
let i = 0, flipped = false;
const save = () => store.set('flash.cards', cards);
const deck = () => ($('#hide').checked ? cards.filter(c => !c.known) : cards);
function render() {
  const d = deck();
  if (i >= d.length) i = Math.max(0, d.length - 1);
  const c = d[i];
  $('#card').textContent = c ? (flipped ? c.back : c.front) : (cards.length ? 'All cards known! 🎉' : 'Add a card to start.');
  $('#card').style.borderColor = flipped ? 'var(--accent)' : 'var(--line)';
  $('#pos').textContent = c ? `Card ${i + 1} of ${d.length} · ${cards.filter(x => x.known).length}/${cards.length} known${c.known ? ' · ✓ known' : ''}` : '';
}
const move = n => { const d = deck(); if (!d.length) return; i = (i + n + d.length) % d.length; flipped = false; render(); };
$('#card').onclick = $('#flip').onclick = () => { flipped = !flipped; render(); };
$('#prev').onclick = () => move(-1); $('#next').onclick = () => move(1);
$('#known').onclick = () => { const c = deck()[i]; if (c) { c.known = !c.known; save(); move($('#hide').checked ? 0 : 1); } };
$('#shuffle').onclick = () => { cards.sort(() => Math.random() - 0.5); i = 0; flipped = false; save(); render(); };
$('#hide').onchange = () => { i = 0; render(); };
$('#del').onclick = () => { const c = deck()[i]; if (c && confirm('Delete this card?')) { cards = cards.filter(x => x !== c); save(); render(); } };
$('#add').onclick = () => { const f = $('#front').value.trim(), b = $('#back').value.trim(); if (!f || !b) return alert('Fill in both sides.'); cards.push({ front: f, back: b, known: false }); save(); $('#front').value = ''; $('#back').value = ''; render(); };
document.addEventListener('keydown', e => { if (e.target.tagName === 'INPUT') return; if (e.key === 'ArrowRight') move(1); if (e.key === 'ArrowLeft') move(-1); if (e.key === ' ') { e.preventDefault(); flipped = !flipped; render(); } });
render();

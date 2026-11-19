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

let colors = [], answer = null, locked = false, score = 0, streak = 0, best = store.get('cg.best', 0);
const rnd = () => `rgb(${[0, 0, 0].map(() => Math.floor(Math.random() * 256)).join(', ')})`;
function round() {
  const n = +$('#mode').value;
  colors = [...Array(n)].map(rnd); answer = colors[Math.floor(Math.random() * n)]; locked = false;
  $('#target').textContent = answer.toUpperCase(); $('#msg').textContent = 'Pick the matching color';
  $('#swatches').replaceChildren(...colors.map(c => el('div', { style: `background:${c};height:90px;border-radius:10px;cursor:pointer;transition:opacity .3s`, onclick: e => guess(c, e.target) })));
}
function guess(c, node) {
  if (locked) return;
  if (c === answer) {
    locked = true; score++; streak++; best = Math.max(best, streak); store.set('cg.best', best);
    $('#msg').textContent = '✅ Correct!'; document.querySelectorAll('#swatches div').forEach(d => (d.style.background = answer));
  } else { node.style.opacity = 0; node.style.pointerEvents = 'none'; streak = 0; $('#msg').textContent = '❌ Try again'; }
  $('#score').textContent = score; $('#streak').textContent = streak; $('#best').textContent = best;
}
$('#new').onclick = round; $('#mode').onchange = round;
$('#best').textContent = best; round();

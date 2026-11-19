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

let secret, tries, lo, hi, over, guesses;
let best = store.get('ng.best', null);
function start() { secret = 1 + Math.floor(Math.random() * 100); tries = 0; lo = 1; hi = 100; over = false; guesses = []; $('#msg').textContent = 'Make a guess!'; $('#guess').disabled = false; $('#guess').value = ''; update(); $('#guess').focus(); }
function update() {
  $('#range').textContent = over ? '' : `It's between ${lo} and ${hi}`;
  $('#tries').textContent = `Attempts: ${tries}`;
  $('#best').textContent = best ? `· best: ${best} attempts` : '';
  $('#guesses').replaceChildren(...guesses.map(([g, hint]) => el('span', { class: 'pill', style: hint === '=' ? 'color:var(--ok);border-color:var(--ok)' : '' }, `${g} ${hint === '=' ? '✓' : hint === '<' ? '↑' : '↓'}`)));
}
function guess() {
  if (over) return;
  const g = parseInt($('#guess').value, 10);
  if (!(g >= 1 && g <= 100)) { $('#msg').textContent = 'Enter a whole number from 1 to 100.'; return; }
  tries++;
  const dist = Math.abs(g - secret);
  $('#heat').style.width = Math.max(4, 100 - dist) + '%';
  $('#heat').style.background = dist <= 5 ? 'var(--bad)' : dist <= 15 ? 'var(--warn)' : 'var(--accent)';
  if (g === secret) {
    over = true; guesses.push([g, '=']); $('#msg').textContent = `🎉 Got it! ${secret} in ${tries} attempt${tries > 1 ? 's' : ''}.`;
    if (!best || tries < best) { best = tries; store.set('ng.best', best); }
    $('#guess').disabled = true;
  } else if (g < secret) { lo = Math.max(lo, g + 1); guesses.push([g, '<']); $('#msg').textContent = `${g} is too low${dist <= 5 ? ' — very close!' : ''}`; }
  else { hi = Math.min(hi, g - 1); guesses.push([g, '>']); $('#msg').textContent = `${g} is too high${dist <= 5 ? ' — very close!' : ''}`; }
  $('#guess').value = ''; update();
}
$('#go').onclick = guess; $('#guess').onkeydown = e => e.key === 'Enter' && guess(); $('#restart').onclick = start;
start();

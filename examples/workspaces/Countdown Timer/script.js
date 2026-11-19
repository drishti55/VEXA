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

let total = 300, remaining = 300, end = null, timer = null;
const fmt = t => { t = Math.max(0, Math.round(t)); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60; return (h ? `${h}:` : '') + `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`; };
function readInput() {
  if ($('#mode').value === 'date') { const t = new Date($('#until').value).getTime(); return t ? Math.max(0, (t - Date.now()) / 1000) : 0; }
  return (+$('#h').value || 0) * 3600 + (+$('#m').value || 0) * 60 + (+$('#s').value || 0);
}
function show() { $('#display').textContent = fmt(remaining); $('#bar').style.width = total ? (100 * (1 - remaining / total)) + '%' : '0'; document.title = timer ? `${fmt(remaining)} · Countdown` : 'Countdown Timer'; }
function tick() {
  remaining = (end - Date.now()) / 1000;
  if (remaining <= 0) { remaining = 0; stop(); $('#display').textContent = "⏰ Time's up!"; [0, 500, 1000].forEach(d => setTimeout(() => beep(880, 300), d)); return; }
  show();
}
function stop() { clearInterval(timer); timer = null; $('#start').disabled = false; $('#pause').disabled = true; show(); }
$('#start').onclick = () => {
  if (remaining <= 0 || remaining === total) { total = remaining = readInput(); }
  if (!(remaining > 0)) return alert('Set a time first.');
  end = Date.now() + remaining * 1000; timer = setInterval(tick, 200); $('#start').disabled = true; $('#pause').disabled = false; tick();
};
$('#pause').onclick = stop;
$('#reset').onclick = () => { stop(); total = remaining = readInput(); show(); };
$('#mode').onchange = () => { const d = $('#mode').value === 'date'; $('#durIn').hidden = d; $('#until').hidden = !d; $('#reset').click(); };
document.querySelectorAll('[data-sec]').forEach(b => (b.onclick = () => { $('#mode').value = 'dur'; $('#mode').onchange(); const s = +b.dataset.sec; $('#h').value = Math.floor(s / 3600); $('#m').value = Math.floor(s % 3600 / 60); $('#s').value = s % 60; $('#reset').click(); }));
['#h', '#m', '#s', '#until'].forEach(id => ($(id).onchange = () => !timer && $('#reset').click()));
show();

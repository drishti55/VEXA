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

const light = $('#light');
let timer = null;
const SOS = [1, 1, 1, 3, 3, 3, 1, 1, 1]; // dot = 1 unit, dash = 3 units
function paint(visible) { light.style.background = visible ? $('#color').value : '#000'; light.style.opacity = $('#bright').value / 100; }
function start() {
  stopPattern(); light.hidden = false; paint(true);
  if (document.fullscreenEnabled) document.documentElement.requestFullscreen().catch(() => {}); // not allowed inside a preview frame
  const mode = $('#mode').value;
  if (mode === 'strobe') { let on = true; timer = setInterval(() => paint((on = !on)), 100); }
  if (mode === 'sos') {
    let i = 0, on = false;
    const step = () => { on = !on; paint(on); const unit = 180; const d = on ? SOS[i] * unit : (i === SOS.length - 1 ? 7 * unit : unit); if (!on) i = (i + 1) % SOS.length; timer = setTimeout(step, d); };
    paint(false); timer = setTimeout(step, 300);
  }
}
function stopPattern() { clearInterval(timer); clearTimeout(timer); timer = null; }
function stop() { stopPattern(); light.hidden = true; try { if (document.fullscreenElement) document.exitFullscreen(); } catch {} }
$('#on').onclick = start; light.onclick = stop;
document.addEventListener('keydown', e => e.key === 'Escape' && stop());
['#color', '#bright'].forEach(s => ($(s).oninput = () => !light.hidden && $('#mode').value === 'steady' && paint(true)));

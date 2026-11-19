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

let phase = 'focus', remaining = 25 * 60, running = false, end = 0, timer = null, count = 0;
let log = store.get('study.log', {});
const mins = p => (+$('#' + (p === 'focus' ? 'focus' : p === 'short' ? 'short' : 'long')).value || 1) * 60;
const fmt = t => { t = Math.max(0, Math.ceil(t)); return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };
function render() {
  $('#display').textContent = fmt(remaining);
  $('#phase').textContent = phase === 'focus' ? '🎯 Focus' : phase === 'short' ? '☕ Short break' : '🌴 Long break';
  $('#start').textContent = running ? 'Pause' : 'Start';
  $('#cycle').textContent = `Session ${count % 4 + 1} of 4 before a long break`;
  const items = log[today()] || [];
  $('#mins').textContent = `· ${items.reduce((s, i) => s + i.min, 0)} min focused`;
  $('#log').replaceChildren(...(items.length ? items.slice().reverse().map(i => el('li', {}, el('span', { class: 'grow' }, i.task || 'Focus session'), el('span', { class: 'muted' }, `${i.min} min · ${i.at}`))) : [el('li', { class: 'muted' }, 'No sessions yet.')]));
  document.title = running ? `${fmt(remaining)} · ${phase}` : 'Study Timer';
}
function next(completed) {
  if (phase === 'focus') {
    if (completed) { count++; log[today()] = [...(log[today()] || []), { task: $('#task').value.trim(), min: Math.round(mins('focus') / 60), at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }]; store.set('study.log', log); }
    phase = count && count % 4 === 0 ? 'long' : 'short';
  } else phase = 'focus';
  remaining = mins(phase); pause(); render();
}
function pause() { running = false; clearInterval(timer); }
$('#start').onclick = () => {
  if (running) { pause(); render(); return; }
  running = true; end = Date.now() + remaining * 1000;
  timer = setInterval(() => { remaining = (end - Date.now()) / 1000; if (remaining <= 0) { beep(660, 250); setTimeout(() => beep(880, 400), 300); next(true); } render(); }, 250);
  render();
};
$('#skip').onclick = () => next(false);
$('#reset').onclick = () => { pause(); remaining = mins(phase); render(); };
['#focus', '#short', '#long'].forEach(id => ($(id).onchange = () => { if (!running) { remaining = mins(phase); render(); } }));
render();

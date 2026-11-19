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

let history = store.get('decide.history', []);
$('#opts').value = store.get('decide.opts', '');
function spin(options, label) {
  if (options.length < 2) return alert('Add at least two options (one per line).');
  const btns = [$('#decide'), $('#yesno')]; btns.forEach(b => (b.disabled = true));
  let n = 0; const total = 18 + Math.floor(Math.random() * 8);
  const tick = () => {
    $('#answer').textContent = options[n % options.length];
    if (++n < total) setTimeout(tick, 40 + n * 6);
    else {
      const pick = options[Math.floor(Math.random() * options.length)];
      $('#answer').textContent = pick; btns.forEach(b => (b.disabled = false));
      history.unshift(`${label}: ${pick}`); history = history.slice(0, 15); store.set('decide.history', history); render();
    }
  };
  tick();
}
function render() { $('#history').replaceChildren(...(history.length ? history.map(h => el('li', {}, h)) : [el('li', { class: 'muted' }, 'Nothing decided yet.')])); }
$('#opts').oninput = () => store.set('decide.opts', $('#opts').value);
$('#decide').onclick = () => spin([...new Set($('#opts').value.split('\n').map(s => s.trim()).filter(Boolean))], 'Picked');
$('#yesno').onclick = () => spin(['Yes ✅', 'No ❌'], 'Yes/No');
render();

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

let picked = store.get('picker.picked', []);
$('#names').value = store.get('picker.names', 'Alice\nBob\nCharlie\nDiana\nEthan');
const names = () => $('#names').value.split('\n').map(s => s.trim()).filter(Boolean);
const pool = () => (($('#remove').checked) ? names().filter(n => !picked.includes(n)) : names());
function render() { $('#left').textContent = `${pool().length} name(s) in the draw`; $('#picked').replaceChildren(...picked.map(p => el('li', {}, p))); }
$('#pick').onclick = () => {
  const p = pool(); if (!p.length) return alert(names().length ? 'Everyone has been picked.' : 'Add some names first.');
  $('#pick').disabled = true; let n = 0;
  const t = setInterval(() => {
    $('#winner').textContent = p[Math.floor(Math.random() * p.length)];
    if (++n > 20) {
      clearInterval(t); const w = p[Math.floor(Math.random() * p.length)]; $('#winner').textContent = `🎉 ${w}`;
      picked.push(w); store.set('picker.picked', picked); $('#pick').disabled = false; render();
    }
  }, 60);
};
$('#names').oninput = () => { store.set('picker.names', $('#names').value); render(); };
$('#remove').onchange = render;
$('#reset').onclick = () => { picked = []; store.set('picker.picked', picked); $('#winner').textContent = '—'; render(); };
render();

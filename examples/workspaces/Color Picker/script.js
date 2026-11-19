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

let rgb = [110, 168, 254];
let palette = store.get('color.palette', []);
const hex = c => '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
function hsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2; let h = 0, s = 0;
  if (mx !== mn) { const d = mx - mn; s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn); h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h *= 60; }
  return `hsl(${Math.round(h)}, ${Math.round(s * 100)}%, ${Math.round(l * 100)}%)`;
}
function render(fromSliders) {
  const hx = hex(rgb); $('#swatch').style.background = hx; if (!fromSliders) buildSliders(); $('#picker').value = hx;
  const formats = { HEX: hx.toUpperCase(), RGB: `rgb(${rgb.join(', ')})`, HSL: hsl(rgb) };
  $('#formats').replaceChildren(...Object.entries(formats).map(([k, v]) => el('div', { class: 'row', style: 'padding:4px 0' }, el('b', { style: 'width:50px' }, k), el('code', { class: 'grow' }, v), el('button', { class: 'small ghost', onclick: e => copyText(v, e.target) }, 'Copy'))));
  $('#palette').replaceChildren(...(palette.length ? palette.map(c => el('div', { title: `${c} — click to load, right-click to remove`, style: `width:44px;height:44px;border-radius:8px;background:${c};cursor:pointer;border:1px solid var(--line)`,
    onclick: () => { rgb = [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)); render(); }, oncontextmenu: e => { e.preventDefault(); palette = palette.filter(x => x !== c); store.set('color.palette', palette); render(); } })) : [el('span', { class: 'muted' }, 'No saved colors.')]));
}
function buildSliders() {
  $('#sliders').replaceChildren(...['R', 'G', 'B'].map((n, i) => el('div', { class: 'row' }, el('b', { style: 'width:16px' }, n),
    el('input', { type: 'range', min: 0, max: 255, value: rgb[i], class: 'grow', oninput: e => { rgb[i] = +e.target.value; e.target.nextSibling.textContent = rgb[i]; render(true); } }), el('span', { style: 'width:32px' }, rgb[i]))));
}
$('#picker').oninput = e => { rgb = [1, 3, 5].map(i => parseInt(e.target.value.slice(i, i + 2), 16)); render(); };
$('#savec').onclick = () => { const h = hex(rgb); if (!palette.includes(h)) palette.push(h); store.set('color.palette', palette); render(); };
$('#clearp').onclick = () => { palette = []; store.set('color.palette', palette); render(); };
render();

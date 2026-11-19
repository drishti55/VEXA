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

let items = store.get('shop.items', []);
const save = () => store.set('shop.items', items);
function render() {
  const left = items.filter(i => !i.bought).length;
  $('#count').textContent = items.length ? `${left} of ${items.length} left to buy` : 'Your list is empty';
  const box = $('#groups'); box.replaceChildren();
  [...new Set(items.map(i => i.cat))].sort().forEach(cat => {
    const ul = el('ul', { class: 'list' });
    items.filter(i => i.cat === cat).forEach(i => ul.append(el('li', {}, el('input', { type: 'checkbox', checked: i.bought, onchange: () => { i.bought = !i.bought; save(); render(); } }),
      el('span', { class: 'grow' + (i.bought ? ' done' : '') }, i.name), el('span', { class: 'pill' }, `× ${i.qty}`),
      el('button', { class: 'small ghost', onclick: () => { items = items.filter(x => x !== i); save(); render(); } }, '✕'))));
    box.append(el('h3', { style: 'margin:12px 0 0;font-size:13px;color:var(--muted);text-transform:uppercase' }, cat), ul);
  });
}
$('#add').onclick = () => {
  const name = $('#item').value.trim(), qty = Math.max(1, parseInt($('#qty').value, 10) || 1), cat = $('#cat').value;
  if (!name) return;
  const same = items.find(i => i.name.toLowerCase() === name.toLowerCase() && !i.bought);
  same ? (same.qty += qty) : items.push({ name, qty, cat, bought: false });
  save(); $('#item').value = ''; $('#qty').value = 1; render();
};
$('#item').onkeydown = e => e.key === 'Enter' && $('#add').click();
$('#clear').onclick = () => { items = items.filter(i => !i.bought); save(); render(); };
render();

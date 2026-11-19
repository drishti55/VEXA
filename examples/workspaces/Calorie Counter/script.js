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

let goal = store.get('cal.goal', 2000);
let log = store.get('cal.log', {});
$('#goal').value = goal;
const items = () => log[today()] || [];
function save() { store.set('cal.log', log); store.set('cal.goal', goal); }
function render() {
  const total = items().reduce((s, i) => s + i.kcal, 0);
  $('#total').textContent = `${total} kcal`;
  $('#bar').style.width = Math.min(100, 100 * total / goal) + '%';
  $('#bar').style.background = total > goal ? 'var(--bad)' : 'var(--ok)';
  $('#left').textContent = total > goal ? `${total - goal} kcal over your goal` : `${goal - total} kcal left`;
  const list = $('#list'); list.replaceChildren();
  items().forEach((i, idx) => list.append(el('li', {}, el('span', { class: 'grow' }, i.food), el('b', {}, `${i.kcal} kcal`),
    el('button', { class: 'small ghost', onclick: () => { log[today()].splice(idx, 1); save(); render(); } }, '✕'))));
  if (!items().length) list.append(el('li', { class: 'muted' }, 'Nothing logged today.'));
}
$('#add').onclick = () => {
  const food = $('#food').value.trim(), kcal = parseInt($('#kcal').value, 10);
  if (!food || !(kcal > 0)) return alert('Enter a food and a positive calorie amount.');
  log[today()] = [...items(), { food, kcal }]; save(); $('#food').value = ''; $('#kcal').value = ''; render();
};
$('#kcal').onkeydown = e => e.key === 'Enter' && $('#add').click();
$('#goal').onchange = () => { const g = parseInt($('#goal').value, 10); if (g > 0) { goal = g; save(); render(); } };
$('#reset').onclick = () => { if (confirm('Clear today\'s log?')) { log[today()] = []; save(); render(); } };
render();

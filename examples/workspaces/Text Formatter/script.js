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

const history = [];
const title = s => s.toLowerCase().replace(/(^|[\s\-_(\[{"'])(\p{L})/gu, (m, p, c) => p + c.toUpperCase());
const ACTIONS = {
  'UPPERCASE': s => s.toUpperCase(),
  'lowercase': s => s.toLowerCase(),
  'Title Case': title,
  'Sentence case': s => s.toLowerCase().replace(/(^\s*|[.!?]\s+)(\p{L})/gu, (m, p, c) => p + c.toUpperCase()),
  'Trim spaces': s => s.split('\n').map(l => l.replace(/[ \t]+/g, ' ').trim()).join('\n'),
  'Remove blank lines': s => s.split('\n').filter(l => l.trim()).join('\n'),
  'Sort lines': s => s.split('\n').sort((a, b) => a.localeCompare(b)).join('\n'),
  'Unique lines': s => [...new Set(s.split('\n'))].join('\n'),
  'Reverse': s => [...s].reverse().join(''),
  'slug-case': s => s.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
  'camelCase': s => s.toLowerCase().replace(/[^a-z0-9]+(.)/g, (m, c) => c.toUpperCase()).replace(/^[^a-z0-9]+/, ''),
};
const t = $('#text');
t.value = store.get('fmt.text', '');
function counts() {
  const s = t.value, words = (s.match(/\S+/g) || []).length;
  $('#counts').textContent = `${s.length} characters · ${words} words · ${s ? s.split('\n').length : 0} lines · ~${Math.max(1, Math.round(words / 200))} min read`;
  store.set('fmt.text', s);
}
$('#actions').replaceChildren(...Object.entries(ACTIONS).map(([name, fn]) => el('button', { class: 'ghost small', onclick: () => { history.push(t.value); t.value = fn(t.value); counts(); } }, name)));
$('#undo').onclick = () => { if (history.length) { t.value = history.pop(); counts(); } };
$('#copy').onclick = e => copyText(t.value, e.target);
t.oninput = counts; counts();

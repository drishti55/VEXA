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

const CATS = {
  Smileys: '😀😃😄😁😆😅😂🤣😊😇🙂😉😍🥰😘😋😛😜🤪😎🤩🥳😏😴🤯🥶🤠🤓😇🙃',
  Animals: '🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮🐷🐸🐵🐔🐧🐦🦆🦉🐺🐗🐴🦄🐝🐛🦋🐌🐞🐢🐍🐙🦑🦀🐠🐬🐳🦈🐊🦒🦓🦘',
  Food: '🍏🍎🍐🍊🍋🍌🍉🍇🍓🫐🍒🍑🥭🍍🥥🥝🍅🥑🥦🌽🥕🧄🥐🍞🧀🥚🍳🥞🧇🥓🍔🍟🍕🌭🥪🌮🌯🍣🍜🍩🍪🎂🍫🍿',
  Travel: '🚗🚕🚙🚌🏎️🚓🚑🚒🚲🛵🏍️✈️🚀🛸🚁⛵🚤🚢🗽🗼🏰🏯🗻🏝️🏜️🌋🏕️🎡🎢🌉',
  Objects: '⌚📱💻⌨️🖥️🖨️🖱️💾📷🎥📺📻🎙️⏰💡🔦🕯️📚📖✏️📌📎✂️🔑🔒🧲🧪🔭🎁🎈🎉',
  Symbols: '❤️🧡💛💚💙💜🖤🤍💯✨⭐🌟💫⚡🔥🌈☀️❄️💧🎵🎶✅❌⭕❓❗♻️🔔',
};
const all = Object.values(CATS).join('');
$('#cat').replaceChildren(el('option', { value: 'All' }, 'All'), ...Object.keys(CATS).map(c => el('option', { value: c }, c)));
const pool = () => [...new Intl.Segmenter().segment($('#cat').value === 'All' ? all : CATS[$('#cat').value])].map(s => s.segment);
let current = [];
function gen() {
  const p = pool(), n = Math.min(50, Math.max(1, parseInt($('#n').value, 10) || 1));
  current = [...Array(n)].map(() => p[Math.floor(Math.random() * p.length)]);
  $('#out').replaceChildren(...current.map(e => el('span', { style: 'cursor:pointer', title: 'Copy', onclick: () => { copyText(e); $('#hint').textContent = `Copied ${e}`; } }, e)));
  $('#hint').textContent = 'Click an emoji to copy it.';
}
$('#go').onclick = gen; $('#cat').onchange = gen;
$('#copyall').onclick = e => copyText(current.join(''), e.target);
gen();

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

function score(a, b) {
  const key = [a, b].map(s => s.trim().toLowerCase().replace(/\s+/g, ' ')).sort().join('|');
  let h = 2166136261;
  for (const ch of key) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
  return Math.abs(h) % 101;
}
const MESSAGES = [[90, 'A match made in the stars ✨'], [70, 'Great chemistry! 💞'], [50, 'There is definitely something there 😊'], [30, 'Friendship could grow into more 🌱'], [0, 'Opposites attract… sometimes 🙃']];
$('#go').onclick = () => {
  const a = $('#a').value, b = $('#b').value;
  if (!a.trim() || !b.trim()) return alert('Enter both names.');
  const p = score(a, b);
  $('#result').hidden = false; $('#pct').textContent = `${p}%`; $('#bar').style.width = '0';
  requestAnimationFrame(() => ($('#bar').style.width = p + '%'));
  $('#msg').textContent = MESSAGES.find(([min]) => p >= min)[1];
};
['#a', '#b'].forEach(s => ($(s).onkeydown = e => e.key === 'Enter' && $('#go').click()));

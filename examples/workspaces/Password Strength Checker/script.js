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

const COMMON = ['password', '123456', '12345678', 'qwerty', 'abc123', 'letmein', 'monkey', 'iloveyou', 'admin', 'welcome', 'dragon', 'football', 'sunshine', 'princess', '111111', 'passw0rd', 'qwerty123', '123123'];
function analyse(pw) {
  const checks = [
    ['At least 12 characters', pw.length >= 12],
    ['Lowercase letter', /[a-z]/.test(pw)],
    ['Uppercase letter', /[A-Z]/.test(pw)],
    ['Number', /[0-9]/.test(pw)],
    ['Symbol', /[^A-Za-z0-9]/.test(pw)],
    ['No 3+ repeated characters (aaa)', !/(.)\1\1/.test(pw)],
    ['No common sequences (abc, 123)', !/(abc|bcd|cde|123|234|345|456|567|678|789|qwe|asd)/i.test(pw)],
    ['Not a common password', !COMMON.some(c => pw.toLowerCase().includes(c))],
  ];
  const pool = (/[a-z]/.test(pw) ? 26 : 0) + (/[A-Z]/.test(pw) ? 26 : 0) + (/[0-9]/.test(pw) ? 10 : 0) + (/[^A-Za-z0-9]/.test(pw) ? 33 : 0);
  let bits = pw.length && pool ? pw.length * Math.log2(pool) : 0;
  const failed = checks.filter(c => !c[1]).length;
  if (!checks[7][1]) bits = Math.min(bits, 10);
  bits -= Math.max(0, failed - 2) * 6;
  const score = pw ? Math.max(0, Math.min(4, Math.floor(bits / 20))) : -1;
  return { checks, bits: Math.max(0, Math.round(bits)), score };
}
const LABELS = [['Very weak', 'var(--bad)'], ['Weak', '#f08a5d'], ['Fair', 'var(--warn)'], ['Strong', '#8bd17c'], ['Very strong', 'var(--ok)']];
function render() {
  const pw = $('#pw').value, r = analyse(pw);
  $('#bar').style.width = pw ? ((r.score + 1) * 20) + '%' : '0';
  $('#bar').style.background = r.score >= 0 ? LABELS[r.score][1] : '';
  $('#label').textContent = r.score >= 0 ? LABELS[r.score][0] : 'Enter a password';
  $('#entropy').textContent = pw ? `≈ ${r.bits} bits of entropy` : '';
  $('#checks').replaceChildren(...r.checks.map(([t, ok]) => el('li', {}, el('span', { style: `color:${ok ? 'var(--ok)' : 'var(--bad)'}` }, ok ? '✔' : '✖'), t)));
  const tips = r.checks.filter(c => !c[1]).map(c => c[0]);
  $('#tips').replaceChildren(...(pw ? (tips.length ? tips.map(t => el('li', {}, `Add: ${t.toLowerCase()}`)) : [el('li', {}, 'Looks great. Use a password manager so you never reuse it.')]) : [el('li', {}, 'Long passphrases of random words are easy to remember and hard to guess.')]));
}
$('#pw').oninput = render;
$('#toggle').onclick = () => { const p = $('#pw'); p.type = p.type === 'password' ? 'text' : 'password'; $('#toggle').textContent = p.type === 'password' ? 'Show' : 'Hide'; };
render();

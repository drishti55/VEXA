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

const ROWS = [
  ['Escape', 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'],
  ['Backquote', 'Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Digit6', 'Digit7', 'Digit8', 'Digit9', 'Digit0', 'Minus', 'Equal', 'Backspace'],
  ['Tab', 'KeyQ', 'KeyW', 'KeyE', 'KeyR', 'KeyT', 'KeyY', 'KeyU', 'KeyI', 'KeyO', 'KeyP', 'BracketLeft', 'BracketRight', 'Backslash'],
  ['CapsLock', 'KeyA', 'KeyS', 'KeyD', 'KeyF', 'KeyG', 'KeyH', 'KeyJ', 'KeyK', 'KeyL', 'Semicolon', 'Quote', 'Enter'],
  ['ShiftLeft', 'KeyZ', 'KeyX', 'KeyC', 'KeyV', 'KeyB', 'KeyN', 'KeyM', 'Comma', 'Period', 'Slash', 'ShiftRight'],
  ['ControlLeft', 'AltLeft', 'MetaLeft', 'Space', 'MetaRight', 'AltRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'ArrowRight'],
];
const LABEL = c => ({ Backquote: '`', Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']', Backslash: '\\', Semicolon: ';', Quote: "'", Comma: ',', Period: '.', Slash: '/',
  ShiftLeft: 'Shift', ShiftRight: 'Shift', ControlLeft: 'Ctrl', AltLeft: 'Alt', AltRight: 'Alt', MetaLeft: '⌘', MetaRight: '⌘', Space: 'Space', ArrowLeft: '←', ArrowUp: '↑', ArrowDown: '↓', ArrowRight: '→', Escape: 'Esc', CapsLock: 'Caps', Backspace: '⌫' }[c] || c.replace(/^(Key|Digit)/, ''));
const WIDE = { Backspace: 2, Tab: 1.5, CapsLock: 1.8, Enter: 2, ShiftLeft: 2.3, ShiftRight: 2.3, Space: 6 };
const tested = new Set();
const keys = {};
$('#kb').replaceChildren(...ROWS.map(r => el('div', { style: 'display:flex;gap:4px;margin-bottom:4px' }, ...r.map(c => (keys[c] = el('div', { style: `flex:${WIDE[c] || 1};min-width:${(WIDE[c] || 1) * 30}px;height:38px;display:grid;place-items:center;border:1px solid var(--line);border-radius:6px;font-size:13px;background:#0b0d11;transition:background .1s` }, LABEL(c)))))));
document.addEventListener('keydown', e => {
  e.preventDefault();
  $('#key').textContent = e.key === ' ' ? 'Space' : e.key;
  $('#detail').textContent = `key "${e.key}" · code ${e.code} · keyCode ${e.keyCode}${e.repeat ? ' · repeat' : ''}`;
  tested.add(e.code);
  const k = keys[e.code]; if (k) { k.style.background = 'var(--accent)'; k.style.color = '#0b1220'; }
  $('#tested').textContent = `${tested.size} keys tested`;
});
document.addEventListener('keyup', e => { const k = keys[e.code]; if (k) { k.style.background = 'rgba(76,195,138,.35)'; k.style.color = ''; } });
$('#reset').onclick = () => { tested.clear(); Object.values(keys).forEach(k => { k.style.background = '#0b0d11'; k.style.color = ''; }); $('#tested').textContent = '0 keys tested'; $('#key').textContent = 'Press a key'; };

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

const detector = 'BarcodeDetector' in window ? new BarcodeDetector({ formats: ['qr_code'] }) : null;
$('#support').textContent = detector ? 'QR detection: supported by this browser.' : 'This browser has no built-in QR detector (BarcodeDetector). Try Chrome or Edge on Android/desktop — the camera view still works.';
let stream = null, scanning = false;
let history = store.get('qr.history', []);
function found(text) {
  $('#result').textContent = text;
  const isUrl = /^https?:\/\//i.test(text); $('#open').hidden = !isUrl; if (isUrl) $('#open').href = text;
  if (history[0] !== text) { history.unshift(text); history = history.slice(0, 15); store.set('qr.history', history); renderHistory(); }
  beep(1200, 120);
}
function renderHistory() { $('#history').replaceChildren(...(history.length ? history.map(h => el('li', { style: 'word-break:break-all' }, h)) : [el('li', { class: 'muted' }, 'Nothing scanned yet.')])); }
async function loop() {
  if (!scanning) return;
  try { const codes = await detector.detect($('#video')); if (codes.length) { found(codes[0].rawValue); $('#status').textContent = 'QR code found ✔'; } } catch { /* frame not ready */ }
  setTimeout(loop, 300);
}
$('#cam').onclick = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    $('#video').srcObject = stream; await $('#video').play();
    $('#status').textContent = detector ? 'Point the camera at a QR code' : 'Camera on (no QR detector in this browser)';
    $('#cam').disabled = true; $('#stop').disabled = false;
    if (detector) { scanning = true; loop(); }
  } catch (e) { $('#status').textContent = `Camera unavailable: ${e.name === 'NotAllowedError' ? 'permission denied' : e.message}. Open the app in its own tab to allow the camera.`; }
};
$('#stop').onclick = () => { scanning = false; stream?.getTracks().forEach(t => t.stop()); $('#video').srcObject = null; $('#status').textContent = 'Camera off'; $('#cam').disabled = false; $('#stop').disabled = true; };
$('#file').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  if (!detector) return ($('#result').textContent = 'This browser cannot decode QR codes (no BarcodeDetector).');
  try { const bmp = await createImageBitmap(f); const codes = await detector.detect(bmp); codes.length ? found(codes[0].rawValue) : ($('#result').textContent = 'No QR code found in that image.'); }
  catch (err) { $('#result').textContent = `Could not read the image: ${err.message}`; }
};
$('#copy').onclick = e => copyText($('#result').textContent, e.target);
renderHistory();

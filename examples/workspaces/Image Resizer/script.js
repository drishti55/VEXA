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

let img = null, ratio = 1, name = 'image';
function load(file) {
  if (!file || !file.type.startsWith('image/')) return alert('Please choose an image file.');
  name = file.name.replace(/\.[^.]+$/, '');
  const url = URL.createObjectURL(file); const i = new Image();
  i.onload = () => { img = i; ratio = i.width / i.height; $('#w').value = i.width; $('#h').value = i.height; $('#orig').textContent = `${file.name} · ${i.width}×${i.height} · ${(file.size / 1024).toFixed(1)} KB`; $('#go').disabled = false; draw(); };
  i.src = url;
}
function draw() {
  const w = Math.max(1, +$('#w').value | 0), h = Math.max(1, +$('#h').value | 0), c = $('#canvas');
  c.width = w; c.height = h; const ctx = c.getContext('2d'); ctx.imageSmoothingQuality = 'high'; ctx.drawImage(img, 0, 0, w, h);
}
$('#file').onchange = e => load(e.target.files[0]);
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => { e.preventDefault(); load(e.dataTransfer.files[0]); });
$('#w').oninput = () => { if ($('#lock').checked && img) $('#h').value = Math.round(+$('#w').value / ratio); };
$('#h').oninput = () => { if ($('#lock').checked && img) $('#w').value = Math.round(+$('#h').value * ratio); };
document.querySelectorAll('[data-scale]').forEach(b => (b.onclick = () => { if (!img) return; $('#w').value = Math.round(img.width * b.dataset.scale); $('#h').value = Math.round(img.height * b.dataset.scale); }));
$('#q').oninput = () => ($('#qv').textContent = Math.round($('#q').value * 100) + '%');
$('#go').onclick = () => {
  draw(); const fmt = $('#fmt').value;
  $('#canvas').toBlob(blob => {
    const a = $('#dl'); a.href = URL.createObjectURL(blob); a.download = `${name}-${$('#canvas').width}x${$('#canvas').height}.${fmt.split('/')[1].replace('jpeg', 'jpg')}`; a.hidden = false;
    $('#outInfo').textContent = `${$('#canvas').width}×${$('#canvas').height} · ${(blob.size / 1024).toFixed(1)} KB`;
  }, fmt, +$('#q').value);
};

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

// Demo tunes are synthesised here as WAV files, so the player works with no downloads.
function synth(notes, bpm = 120) {
  const rate = 22050, beat = 60 / bpm, len = Math.ceil(notes.reduce((s, n) => s + n[1], 0) * beat * rate);
  const data = new Int16Array(len); let t = 0;
  notes.forEach(([note, beats]) => {
    const n = Math.floor(beats * beat * rate), f = note ? 440 * 2 ** ((note - 69) / 12) : 0;
    for (let i = 0; i < n && t + i < len; i++) { const env = Math.min(1, i / 300) * Math.max(0, 1 - i / n); data[t + i] = f ? Math.round(9000 * env * (Math.sin(2 * Math.PI * f * i / rate) + 0.3 * Math.sin(4 * Math.PI * f * i / rate))) : 0; }
    t += n;
  });
  const buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf), w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, 'RIFF'); v.setUint32(4, 36 + len * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, len * 2, true);
  new Int16Array(buf, 44).set(data);
  return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
}
const ode = [[64, 1], [64, 1], [65, 1], [67, 1], [67, 1], [65, 1], [64, 1], [62, 1], [60, 1], [60, 1], [62, 1], [64, 1], [64, 1.5], [62, 0.5], [62, 2]];
const twinkle = [[60, 1], [60, 1], [67, 1], [67, 1], [69, 1], [69, 1], [67, 2], [65, 1], [65, 1], [64, 1], [64, 1], [62, 1], [62, 1], [60, 2]];
const arp = [...Array(4)].flatMap((_, k) => [[57 + (k % 2) * 3, 0.5], [60 + (k % 2) * 3, 0.5], [64 + (k % 2) * 3, 0.5], [69 + (k % 2) * 3, 0.5]]);
let tracks = [
  { title: 'Ode to Joy (demo)', artist: 'Beethoven · synthesised', src: synth(ode, 132) },
  { title: 'Twinkle Twinkle (demo)', artist: 'Traditional · synthesised', src: synth(twinkle, 120) },
  { title: 'Arpeggio Loop (demo)', artist: 'VEXA · synthesised', src: synth([...arp, ...arp], 140) },
];
let idx = 0, shuffle = false, repeat = true;
const audio = $('#audio');
const fmt = s => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '0:00');
function load(i, play = true) { idx = (i + tracks.length) % tracks.length; const t = tracks[idx]; audio.src = t.src; $('#title').textContent = t.title; $('#meta').textContent = t.artist; render(); if (play) audio.play().catch(() => {}); }
function render() { $('#list').replaceChildren(...tracks.map((t, i) => el('li', { style: `cursor:pointer;${i === idx ? 'color:var(--accent);font-weight:600' : ''}`, onclick: () => load(i) }, el('span', {}, i === idx && !audio.paused ? '▶' : `${i + 1}.`), el('span', { class: 'grow' }, t.title), el('span', { class: 'muted' }, t.artist)))); $('#play').textContent = audio.paused ? '▶' : '⏸'; }
function next() { load(shuffle ? Math.floor(Math.random() * tracks.length) : idx + 1); }
$('#play').onclick = () => { if (!audio.src) return load(0); audio.paused ? audio.play() : audio.pause(); };
$('#next').onclick = next; $('#prev').onclick = () => (audio.currentTime > 3 ? (audio.currentTime = 0) : load(idx - 1));
$('#shuffle').onclick = () => { shuffle = !shuffle; $('#shuffle').style.borderColor = shuffle ? 'var(--accent)' : ''; };
$('#repeat').onclick = () => { repeat = !repeat; $('#repeat').style.borderColor = repeat ? 'var(--accent)' : ''; };
$('#repeat').style.borderColor = 'var(--accent)';
$('#vol').oninput = () => (audio.volume = +$('#vol').value); audio.volume = 0.8;
audio.onplay = audio.onpause = render;
audio.ontimeupdate = () => { $('#cur').textContent = fmt(audio.currentTime); $('#dur').textContent = fmt(audio.duration); if (audio.duration) $('#seek').value = 100 * audio.currentTime / audio.duration; };
audio.onended = () => (repeat || idx < tracks.length - 1 ? next() : render());
$('#seek').oninput = () => { if (audio.duration) audio.currentTime = $('#seek').value / 100 * audio.duration; };
$('#files').onchange = e => { const added = [...e.target.files].map(f => ({ title: f.name.replace(/\.[^.]+$/, ''), artist: `${(f.size / 1048576).toFixed(1)} MB · your file`, src: URL.createObjectURL(f) })); if (!added.length) return; tracks = [...tracks, ...added]; load(tracks.length - added.length); };
document.addEventListener('keydown', e => { if (e.key === ' ' && e.target.tagName !== 'INPUT') { e.preventDefault(); $('#play').click(); } });
load(0, false);

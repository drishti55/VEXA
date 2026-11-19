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

const RECIPES = [
  { name: 'Spaghetti Aglio e Olio', time: 15, diet: ['vegetarian', 'vegan'], ing: ['spaghetti', 'garlic', 'olive oil', 'chili flakes', 'parsley'], steps: ['Boil the pasta.', 'Gently fry sliced garlic and chili in olive oil.', 'Toss with pasta, a splash of pasta water and parsley.'] },
  { name: 'Tomato Omelette', time: 10, diet: ['vegetarian', 'gluten-free'], ing: ['egg', 'tomato', 'onion', 'salt', 'butter'], steps: ['Whisk eggs with salt.', 'Soften onion and tomato in butter.', 'Pour in eggs, cook until just set, fold.'] },
  { name: 'Chickpea Curry', time: 30, diet: ['vegetarian', 'vegan', 'gluten-free'], ing: ['chickpeas', 'onion', 'garlic', 'tomato', 'coconut milk', 'curry powder'], steps: ['Fry onion and garlic.', 'Add curry powder, then tomato.', 'Add chickpeas and coconut milk; simmer 15 min.'] },
  { name: 'Grilled Cheese Sandwich', time: 10, diet: ['vegetarian'], ing: ['bread', 'cheese', 'butter'], steps: ['Butter the bread outsides.', 'Fill with cheese.', 'Cook in a pan until golden on both sides.'] },
  { name: 'Chicken Stir-Fry', time: 25, diet: [], ing: ['chicken', 'bell pepper', 'soy sauce', 'garlic', 'ginger', 'rice'], steps: ['Cook rice.', 'Stir-fry chicken until browned.', 'Add vegetables, garlic, ginger and soy sauce; toss 3 min.'] },
  { name: 'Greek Salad', time: 10, diet: ['vegetarian', 'gluten-free'], ing: ['tomato', 'cucumber', 'feta', 'olive', 'onion', 'olive oil'], steps: ['Chop the vegetables.', 'Add olives and feta.', 'Dress with olive oil and oregano.'] },
  { name: 'Pancakes', time: 20, diet: ['vegetarian'], ing: ['flour', 'milk', 'egg', 'sugar', 'baking powder', 'butter'], steps: ['Whisk dry ingredients, then add milk and egg.', 'Rest 5 minutes.', 'Cook ladlefuls in a buttered pan, flip when bubbles form.'] },
  { name: 'Lentil Soup', time: 40, diet: ['vegetarian', 'vegan', 'gluten-free'], ing: ['lentils', 'carrot', 'onion', 'celery', 'garlic', 'cumin'], steps: ['Soften the vegetables.', 'Add lentils, cumin and water.', 'Simmer 30 min, then blend half.'] },
  { name: 'Guacamole', time: 10, diet: ['vegetarian', 'vegan', 'gluten-free'], ing: ['avocado', 'lime', 'onion', 'tomato', 'cilantro', 'salt'], steps: ['Mash avocados.', 'Stir in lime, chopped onion, tomato and cilantro.', 'Season with salt.'] },
  { name: 'Banana Smoothie', time: 5, diet: ['vegetarian', 'gluten-free'], ing: ['banana', 'milk', 'yogurt', 'honey'], steps: ['Blend everything until smooth.'] },
  { name: 'Fried Rice', time: 20, diet: ['vegetarian'], ing: ['rice', 'egg', 'peas', 'carrot', 'soy sauce', 'spring onion'], steps: ['Scramble the egg and set aside.', 'Fry vegetables, add cold rice.', 'Add soy sauce and egg, toss well.'] },
  { name: 'Baked Salmon', time: 25, diet: ['gluten-free'], ing: ['salmon', 'lemon', 'garlic', 'olive oil', 'dill'], steps: ['Heat oven to 200 °C.', 'Top salmon with garlic, lemon, dill and oil.', 'Bake 12–15 minutes.'] },
];
function render() {
  const q = $('#q').value.toLowerCase().trim(), have = $('#have').value.toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
  const diet = $('#diet').value, max = +$('#time').value;
  const rows = RECIPES.filter(r => (!q || r.name.toLowerCase().includes(q) || r.ing.some(i => i.includes(q))) && (!diet || r.diet.includes(diet)) && r.time <= max)
    .map(r => ({ r, got: have.length ? r.ing.filter(i => have.some(h => i.includes(h) || h.includes(i))) : [] }))
    .sort((a, b) => have.length ? b.got.length / b.r.ing.length - a.got.length / a.r.ing.length : a.r.name.localeCompare(b.r.name));
  $('#count').textContent = `${rows.length} recipe(s)`;
  $('#results').replaceChildren(...(rows.length ? rows.map(({ r, got }) => el('div', { class: 'card', style: 'cursor:pointer', onclick: () => show(r, got) },
    el('div', { class: 'row' }, el('b', { class: 'grow' }, r.name), el('span', { class: 'pill' }, `${r.time} min`), ...r.diet.map(d => el('span', { class: 'pill' }, d))),
    el('p', { class: 'muted', style: 'margin:6px 0 0' }, have.length ? `You have ${got.length}/${r.ing.length} · missing: ${r.ing.filter(i => !got.includes(i)).join(', ') || 'nothing! 🎉'}` : r.ing.join(', '))))
    : [el('div', { class: 'card muted center' }, 'No recipes match. Try fewer filters.')]));
}
function show(r, got) {
  const d = $('#dlg');
  d.replaceChildren(el('h2', { style: 'margin-top:0' }, r.name), el('p', { class: 'muted' }, `${r.time} minutes${r.diet.length ? ' · ' + r.diet.join(', ') : ''}`),
    el('b', {}, 'Ingredients'), el('ul', {}, ...r.ing.map(i => el('li', { style: got.includes(i) ? 'color:var(--ok)' : '' }, i + (got.includes(i) ? ' ✓' : '')))),
    el('b', {}, 'Steps'), el('ol', {}, ...r.steps.map(s => el('li', {}, s))), el('button', { onclick: () => d.close() }, 'Close'));
  d.showModal();
}
['#q', '#have'].forEach(s => ($(s).oninput = render)); ['#diet', '#time'].forEach(s => ($(s).onchange = render));
render();

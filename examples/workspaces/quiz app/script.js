// script.js
// Accessible Quiz Application

const quizContainer = document.getElementById('quiz-container');
const questionArea = document.getElementById('question-area');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');
const resultArea = document.getElementById('result-area');
const restartBtn = document.getElementById('restart-btn');

let quizData = [];
let currentQuestionIndex = 0;
let userAnswers = [];

// Utility to create elements with attributes
function createElement(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') el.className = value;
    else if (key === 'htmlFor') el.htmlFor = value;
    else if (key === 'innerHTML') el.innerHTML = value;
    else if (key === 'textContent') el.textContent = value;
    else if (key === 'id') el.id = value;
    else if (key === 'name') el.name = value;
    else if (key === 'value') el.value = value;
    else if (key === 'type') el.type = value;
    else if (key === 'checked') el.checked = value;
    else if (key === 'disabled') el.disabled = value;
    else if (key === 'tabindex') el.tabIndex = value;
    else if (key === 'ariaLabel') el.setAttribute('aria-label', value);
    else el.setAttribute(key, value);
  }
  for (const child of children) {
    if (typeof child === 'string') el.appendChild(document.createTextNode(child));
    else if (child instanceof Node) el.appendChild(child);
  }
  return el;
}

function loadQuizData() {
  return fetch('data.json')
    .then((response) => {
      if (!response.ok) throw new Error('Network response was not ok');
      return response.json();
    })
    .then((data) => {
      if (!Array.isArray(data.questions)) throw new Error('Invalid quiz data');
      quizData = data.questions;
      userAnswers = Array(quizData.length).fill(null);
      renderQuestion();
      updateNavigation();
    })
    .catch((err) => {
      questionArea.innerHTML = `<p class="error">Error loading quiz: ${err.message}</p>`;
      prevBtn.disabled = true;
      nextBtn.disabled = true;
    });
}

function renderQuestion() {
  const q = quizData[currentQuestionIndex];
  questionArea.innerHTML = '';
  const questionEl = createElement('h2', { class: 'question-text' }, q.question);
  questionArea.appendChild(questionEl);

  const form = createElement('form', { id: 'options-form' });
  q.options.forEach((opt, idx) => {
    const optionId = `option-${idx}`;
    const radio = createElement('input', {
      type: 'radio',
      name: 'option',
      id: optionId,
      value: idx,
      checked: userAnswers[currentQuestionIndex] === idx,
      tabindex: 0,
    });
    const label = createElement('label', { htmlFor: optionId, class: 'option-label' }, opt);
    const wrapper = createElement('div', { class: 'option-wrapper' }, radio, label);
    form.appendChild(wrapper);
  });
  questionArea.appendChild(form);
}

function updateNavigation() {
  prevBtn.disabled = currentQuestionIndex === 0;
  if (currentQuestionIndex === quizData.length - 1) {
    nextBtn.textContent = 'Submit';
  } else {
    nextBtn.textContent = 'Next';
  }
}

function recordAnswer() {
  const form = document.getElementById('options-form');
  const selected = form.querySelector('input[name="option"]:checked');
  if (selected) {
    userAnswers[currentQuestionIndex] = parseInt(selected.value, 10);
  } else {
    userAnswers[currentQuestionIndex] = null;
  }
}

function calculateScore() {
  let correct = 0;
  quizData.forEach((q, idx) => {
    if (userAnswers[idx] === q.correct) correct += 1;
  });
  return { correct, total: quizData.length };
}

function showResult() {
  const { correct, total } = calculateScore();
  const percentage = (correct / total) * 100;
  let message = '';
  if (percentage === 100) {
    message = 'Excellent! You got all questions right.';
  } else if (percentage >= 70) {
    message = 'Good job! You scored ' + percentage.toFixed(0) + '%.';
  } else {
    message = 'You scored ' + percentage.toFixed(0) + '. Keep practicing!';
  }
  resultArea.innerHTML = `<p>Your score: ${correct} / ${total} (${percentage.toFixed(0)}%)</p><p>${message}</p>`;
  resultArea.hidden = false;
  restartBtn.hidden = false;
  questionArea.hidden = true;
  prevBtn.hidden = true;
  nextBtn.hidden = true;
}

function restartQuiz() {
  currentQuestionIndex = 0;
  userAnswers = Array(quizData.length).fill(null);
  resultArea.hidden = true;
  restartBtn.hidden = true;
  questionArea.hidden = false;
  prevBtn.hidden = false;
  nextBtn.hidden = false;
  renderQuestion();
  updateNavigation();
}

prevBtn.addEventListener('click', () => {
  recordAnswer();
  if (currentQuestionIndex > 0) {
    currentQuestionIndex -= 1;
    renderQuestion();
    updateNavigation();
  }
});

nextBtn.addEventListener('click', () => {
  recordAnswer();
  if (currentQuestionIndex < quizData.length - 1) {
    currentQuestionIndex += 1;
    renderQuestion();
    updateNavigation();
  } else {
    showResult();
  }
});

restartBtn.addEventListener('click', restartQuiz);

// Initialize
loadQuizData();

// Expose for testing
window.__quiz = {
  getState: () => ({
    currentQuestionIndex,
    userAnswers,
    quizData,
  }),
  recordAnswer,
  calculateScore,
  showResult,
};

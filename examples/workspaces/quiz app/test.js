// test.js
// Simple test harness for the quiz application

function log(msg, passed) {
  const color = passed ? 'green' : 'red';
  console.log(`%c${msg}`, `color:${color}`);
}

function waitForQuizData(timeout = 2000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const interval = setInterval(() => {
      const state = window.__quiz.getState();
      if (state.quizData && state.quizData.length > 0) {
        clearInterval(interval);
        resolve(state);
      } else if (Date.now() - start > timeout) {
        clearInterval(interval);
        reject(new Error('Quiz data not loaded in time'));
      }
    }, 50);
  });
}

function clickButton(id) {
  const btn = document.getElementById(id);
  if (!btn) throw new Error(`Button ${id} not found`);
  btn.click();
}

function selectOption(index) {
  const form = document.getElementById('options-form');
  const radio = form.querySelector(`input[value="${index}"]`);
  if (!radio) throw new Error(`Option ${index} not found`);
  radio.checked = true;
  // dispatch change event to ensure any listeners
  const event = new Event('change', { bubbles: true });
  radio.dispatchEvent(event);
}

async function runTests() {
  try {
    const state = await waitForQuizData();
    const total = state.quizData.length;

    // Test 1: Initial state
    log('Test 1: Initial state', state.currentQuestionIndex === 0 && state.userAnswers.every(a => a === null));

    // Test 2: Select first option for first question and go next
    selectOption(0);
    clickButton('next-btn');
    const state2 = window.__quiz.getState();
    log('Test 2: Answer recorded and moved to next', state2.currentQuestionIndex === 1 && state2.userAnswers[0] === 0);

    // Test 3: Go back and check selection persists
    clickButton('prev-btn');
    const state3 = window.__quiz.getState();
    const form = document.getElementById('options-form');
    const checked = form.querySelector('input:checked');
    log('Test 3: Selection persists after back', checked && parseInt(checked.value, 10) === 0);

    // Test 4: Navigate to last question and answer all correctly
    for (let i = 1; i < total; i++) {
      // select correct answer
      const correctIdx = state.quizData[i].correct;
      selectOption(correctIdx);
      if (i < total - 1) clickButton('next-btn');
    }
    // Now on last question, submit
    const lastCorrect = state.quizData[total - 1].correct;
    selectOption(lastCorrect);
    clickButton('next-btn'); // submit

    const score = window.__quiz.calculateScore();
    log('Test 4: Score calculation', score.correct === total && score.total === total);

    // Test 5: Result area visible
    const resultArea = document.getElementById('result-area');
    log('Test 5: Result area displayed', !resultArea.hidden);

    // Test 6: Restart quiz resets state
    clickButton('restart-btn');
    const stateAfterRestart = window.__quiz.getState();
    log('Test 6: Restart resets state', stateAfterRestart.currentQuestionIndex === 0 && stateAfterRestart.userAnswers.every(a => a === null));

    log('All tests completed.', true);
  } catch (e) {
    console.error('Test harness error:', e);
  }
}

runTests();

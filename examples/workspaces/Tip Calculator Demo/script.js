document.addEventListener('DOMContentLoaded', () => {
  const billInput = document.getElementById('bill');
  const tipSelect = document.getElementById('tip');
  const peopleInput = document.getElementById('people');
  const calcButton = document.getElementById('calc');
  const resultDiv = document.getElementById('result');

  function validateNumber(value, name) {
    const num = parseFloat(value);
    if (isNaN(num) || num <= 0) {
      throw new Error(`${name} must be a positive number`);
    }
    return num;
  }

  calcButton.addEventListener('click', () => {
    try {
      const bill = validateNumber(billInput.value, 'Bill');
      const tipPercent = validateNumber(tipSelect.value, 'Tip');
      const people = validateNumber(peopleInput.value, 'People');

      const tipAmount = bill * (tipPercent / 100);
      const total = bill + tipAmount;
      const perPerson = total / people;

      resultDiv.textContent = `Tip: $${tipAmount.toFixed(2)} | Total: $${total.toFixed(2)} | Per Person: $${perPerson.toFixed(2)}`;
    } catch (e) {
      resultDiv.textContent = e.message;
    }
  });
});

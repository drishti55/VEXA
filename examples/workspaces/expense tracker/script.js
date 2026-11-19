const expenses = [];

const form = document.getElementById('expense-form');
const nameInput = document.getElementById('expense-name');
const amountInput = document.getElementById('expense-amount');
const errorMessage = document.getElementById('error-message');
const expenseList = document.getElementById('expense-list');
const totalAmount = document.getElementById('total-amount');

function formatCurrency(value) {
    return Number(value).toFixed(2);
}

function renderExpense(expense, index) {
    const li = document.createElement('li');
    li.dataset.index = index;
    li.innerHTML = `<span>${expense.name}</span> <span>$${formatCurrency(expense.amount)}</span> <button class="delete-btn" aria-label="Delete ${expense.name}">✕</button>`;
    expenseList.appendChild(li);
}

function updateTotal() {
    const total = expenses.reduce((sum, exp) => sum + exp.amount, 0);
    totalAmount.textContent = `Total: $${formatCurrency(total)}`;
}

function showError(message) {
    errorMessage.textContent = message;
    setTimeout(() => {
        errorMessage.textContent = '';
    }, 3000);
}

form.addEventListener('submit', function (e) {
    e.preventDefault();
    const name = nameInput.value.trim();
    const amount = parseFloat(amountInput.value);

    if (!name) {
        showError('Expense name cannot be empty.');
        return;
    }
    if (isNaN(amount) || amount <= 0) {
        showError('Amount must be a positive number.');
        return;
    }

    const expense = { name, amount };
    expenses.push(expense);
    renderExpense(expense, expenses.length - 1);
    updateTotal();
    form.reset();
});

expenseList.addEventListener('click', function (e) {
    if (e.target.classList.contains('delete-btn')) {
        const li = e.target.closest('li');
        const index = parseInt(li.dataset.index, 10);
        expenses.splice(index, 1);
        li.remove();
        // Reindex remaining items
        const lis = expenseList.querySelectorAll('li');
        lis.forEach((item, idx) => {
            item.dataset.index = idx;
        });
        updateTotal();
    }
});

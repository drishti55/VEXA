// app.js
// Simple To-Do List application with localStorage persistence

const STORAGE_KEY = 'todo_tasks';

// Utility to get tasks from localStorage
function loadTasks() {
    const data = localStorage.getItem(STORAGE_KEY);
    if (!data) return [];
    try {
        const parsed = JSON.parse(data);
        if (Array.isArray(parsed)) return parsed;
    } catch (e) {
        console.error('Failed to parse tasks from localStorage', e);
    }
    return [];
}

// Save tasks array to localStorage
function saveTasks(tasks) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
    } catch (e) {
        console.error('Failed to save tasks to localStorage', e);
    }
}

// Render the task list
function renderTasks() {
    const taskList = document.getElementById('task-list');
    taskList.innerHTML = '';
    tasks.forEach((task, index) => {
        const li = document.createElement('li');
        li.className = 'task-item' + (task.completed ? ' completed' : '');

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'task-checkbox';
        checkbox.checked = task.completed;
        checkbox.addEventListener('change', () => {
            task.completed = checkbox.checked;
            saveTasks(tasks);
            renderTasks();
        });

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'task-text';
        input.value = task.text;
        input.readOnly = true;
        input.addEventListener('dblclick', () => {
            enterEditMode(input, task);
        });

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'task-actions';

        const editBtn = document.createElement('button');
        editBtn.textContent = 'Edit';
        editBtn.className = 'edit-btn';
        editBtn.addEventListener('click', () => {
            enterEditMode(input, task);
        });

        const deleteBtn = document.createElement('button');
        deleteBtn.textContent = 'Delete';
        deleteBtn.className = 'delete-btn';
        deleteBtn.addEventListener('click', () => {
            tasks.splice(index, 1);
            saveTasks(tasks);
            renderTasks();
        });

        actionsDiv.appendChild(editBtn);
        actionsDiv.appendChild(deleteBtn);

        li.appendChild(checkbox);
        li.appendChild(input);
        li.appendChild(actionsDiv);

        taskList.appendChild(li);
    });
}

function enterEditMode(inputEl, task) {
    inputEl.readOnly = false;
    inputEl.classList.add('editing');
    inputEl.focus();
    inputEl.select();

    const finish = () => {
        const newText = inputEl.value.trim();
        if (newText) {
            task.text = newText;
            saveTasks(tasks);
        } else {
            // If empty, delete the task
            const idx = tasks.indexOf(task);
            if (idx !== -1) {
                tasks.splice(idx, 1);
                saveTasks(tasks);
            }
        }
        inputEl.readOnly = true;
        inputEl.classList.remove('editing');
        renderTasks();
    };

    inputEl.addEventListener('blur', finish, { once: true });
    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            inputEl.blur();
        }
    }, { once: true });
}

// Global tasks array
let tasks = loadTasks();

// Add event listeners for adding tasks
document.getElementById('add-task-btn').addEventListener('click', () => {
    const input = document.getElementById('new-task-input');
    const text = input.value.trim();
    if (!text) return;
    tasks.push({ text, completed: false });
    saveTasks(tasks);
    renderTasks();
    input.value = '';
});

// Initial render
renderTasks();

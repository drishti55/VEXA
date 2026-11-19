"use strict";

// Constants
const STORAGE_KEY = 'notesAppData';

// Placeholder notes array
let notes = [];
let editingNoteId = null;

// Utility function: Load notes from Local Storage
function loadNotes() {
    // Load notes from Local Storage into the `notes` array.
    notes = getNotes();
}

// Utility function: Save notes to Local Storage
function saveNotes(notes) {
    // Save the provided notes array to Local Storage.
    if (typeof window === 'undefined' || !window.localStorage) {
        console.warn('Local Storage is not available.');
        return;
    }
    try {
        const data = JSON.stringify(notes);
        localStorage.setItem(STORAGE_KEY, data);
    } catch (e) {
        if (e && e.name === 'QuotaExceededError') {
            console.error('Local storage quota exceeded.', e);
            showToast('Storage quota exceeded.');
        } else {
            console.error('Error saving notes to Local Storage.', e);
            showToast('Error saving notes.');
        }
    }
}

// Utility function: Get notes from Local Storage
function getNotes() {
    if (typeof window === 'undefined' || !window.localStorage) {
        console.warn('Local Storage is not available.');
        return [];
    }
    try {
        const data = localStorage.getItem(STORAGE_KEY);
        if (!data) {
            return [];
        }
        const parsed = JSON.parse(data);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        console.error('Error reading notes from Local Storage.', e);
        return [];
    }
}

// Utility function: Generate a unique identifier for a note
function generateId() {
    // Generate a unique ID using timestamp and random component
    return `${Date.now()}-${Math.random()}`;
}

// Utility function: Show a toast message
let toastTimeout = null;
function showToast(message) {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('visible');
    if (toastTimeout) {
        clearTimeout(toastTimeout);
    }
    toastTimeout = setTimeout(() => {
        toast.classList.remove('visible');
        toastTimeout = null;
    }, 3000);
}

// Utility function: Render notes list
function renderNotes() {
    const notesList = document.getElementById('notes-list');
    if (!notesList) return;
    // Clear existing notes
    notesList.innerHTML = '';
    notes.forEach(note => {
        const noteCard = document.createElement('div');
        noteCard.className = 'note-card';
        noteCard.dataset.id = note.id;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'note-content';
        const titleEl = document.createElement('h3');
        titleEl.textContent = note.title;
        const bodyEl = document.createElement('p');
        bodyEl.textContent = note.body;
        contentDiv.appendChild(titleEl);
        contentDiv.appendChild(bodyEl);

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'note-actions';
        const editBtn = document.createElement('button');
        editBtn.className = 'edit-note-btn';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', () => {
            // Populate form for editing
            editingNoteId = note.id;
            document.getElementById('note-title').value = note.title;
            document.getElementById('note-body').value = note.body;
            document.getElementById('add-note-form').style.display = 'flex';
        });
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'delete-note-btn';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', () => {
            // Delete-note workflow: confirm, remove, save, re-render, toast
            const confirmed = window.confirm('Are you sure you want to delete this note?');
            if (!confirmed) return;
            notes = notes.filter(n => n.id !== note.id);
            saveNotes(notes);
            renderNotes();
            showToast('Note deleted');
        });
        actionsDiv.appendChild(editBtn);
        actionsDiv.appendChild(deleteBtn);

        noteCard.appendChild(contentDiv);
        noteCard.appendChild(actionsDiv);
        notesList.appendChild(noteCard);
    });
}

// Register event listeners after DOM content is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Load existing notes and render
    loadNotes();
    renderNotes();

    const addNoteBtn = document.querySelector('.add-note-btn');
    const addNoteForm = document.getElementById('add-note-form');
    const cancelBtn = document.querySelector('.cancel-note-btn');
    const titleInput = document.getElementById('note-title');
    const bodyInput = document.getElementById('note-body');

    // Show form when Add Note button is clicked
    if (addNoteBtn) {
        addNoteBtn.addEventListener('click', () => {
            addNoteForm.style.display = 'flex';
            // Reset form for new note
            editingNoteId = null;
            titleInput.value = '';
            bodyInput.value = '';
        });
    }

    // Cancel button hides form and resets state
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            addNoteForm.style.display = 'none';
            editingNoteId = null;
            titleInput.value = '';
            bodyInput.value = '';
        });
    }

    // Handle form submission for add or edit
    if (addNoteForm) {
        addNoteForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const title = titleInput.value.trim();
            const body = bodyInput.value.trim();
            if (!title || !body) {
                showToast('Title and body cannot be empty');
                return;
            }
            if (editingNoteId) {
                // Edit existing note
                const note = notes.find(n => n.id === editingNoteId);
                if (note) {
                    note.title = title;
                    note.body = body;
                    saveNotes(notes);
                    renderNotes();
                    showToast('Note updated');
                }
                editingNoteId = null;
            } else {
                // Add new note
                const newNote = {
                    id: generateId(),
                    title,
                    body
                };
                notes.push(newNote);
                saveNotes(notes);
                renderNotes();
                showToast('Note added');
            }
            // Reset form
            addNoteForm.style.display = 'none';
            titleInput.value = '';
            bodyInput.value = '';
        });
    }
});

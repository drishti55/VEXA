// script.js
// Password Generator Implementation

// Character sets
const UPPERCASE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const LOWERCASE = 'abcdefghijklmnopqrstuvwxyz';
const DIGITS = '0123456789';
const SYMBOLS = '!@#$%^&*()-_=+[]{}|;:,.<>?';
const ALL_CHARS = UPPERCASE + LOWERCASE + DIGITS + SYMBOLS;

/**
 * Generate a cryptographically secure password of given length.
 * Ensures at least one character from each required set.
 * @param {number} length
 * @returns {string}
 */
function generatePassword(length) {
    if (length < 4) throw new Error('Password length must be at least 4');
    const passwordChars = [];
    // Ensure one from each set
    passwordChars.push(randomCharFrom(UPPERCASE));
    passwordChars.push(randomCharFrom(LOWERCASE));
    passwordChars.push(randomCharFrom(DIGITS));
    passwordChars.push(randomCharFrom(SYMBOLS));

    const remaining = length - 4;
    for (let i = 0; i < remaining; i++) {
        passwordChars.push(randomCharFrom(ALL_CHARS));
    }

    // Shuffle to randomize positions
    shuffleArray(passwordChars);
    return passwordChars.join('');
}

/**
 * Get a random character from a string using crypto.getRandomValues.
 * @param {string} chars
 * @returns {string}
 */
function randomCharFrom(chars) {
    const array = new Uint32Array(1);
    window.crypto.getRandomValues(array);
    const index = array[0] % chars.length;
    return chars.charAt(index);
}

/**
 * Shuffle array in place using Fisher-Yates algorithm.
 * @param {Array} array
 */
function shuffleArray(array) {
    for (let i = array.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
}

/**
 * Validate password length input.
 * @param {string|number} value
 * @returns {{valid: boolean, error: string|null}}
 */
function validateLength(value) {
    const num = Number(value);
    if (!Number.isInteger(num)) {
        return { valid: false, error: 'Length must be an integer.' };
    }
    if (num < 4 || num > 128) {
        return { valid: false, error: 'Length must be between 4 and 128.' };
    }
    return { valid: true, error: null };
}

/**
 * Show a temporary message in the #message element.
 * @param {string} text
 * @param {number} duration - milliseconds
 */
function showMessage(text, duration = 2000) {
    const msgEl = document.getElementById('message');
    if (!msgEl) return;
    msgEl.textContent = text;
    msgEl.classList.add('show');
    clearTimeout(msgEl._timeoutId);
    msgEl._timeoutId = setTimeout(() => {
        msgEl.classList.remove('show');
    }, duration);
}

/**
 * Copy text to clipboard with fallback.
 * @param {string} text
 * @returns {Promise<void>}
 */
async function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (e) {
            // fall back
        }
    }
    // Fallback using textarea
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
    } finally {
        document.body.removeChild(textarea);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const lengthInput = document.getElementById('lengthInput');
    const generateBtn = document.getElementById('generateBtn');
    const passwordOutput = document.getElementById('passwordOutput');
    const copyBtn = document.getElementById('copyBtn');
    copyBtn.disabled = true;

    function updateGenerateButton() {
        const { valid } = validateLength(lengthInput.value);
        generateBtn.disabled = !valid;
    }

    lengthInput.addEventListener('input', updateGenerateButton);
    updateGenerateButton();

    generateBtn.addEventListener('click', () => {
        const { valid, error } = validateLength(lengthInput.value);
        if (!valid) {
            showMessage(error, 3000);
            return;
        }
        const length = Number(lengthInput.value);
        const pwd = generatePassword(length);
        passwordOutput.value = pwd;
        copyBtn.disabled = false;
        showMessage('Password generated', 2000);
    });

    copyBtn.addEventListener('click', async () => {
        const pwd = passwordOutput.value;
        if (!pwd) return;
        await copyToClipboard(pwd);
        showMessage('Copied!', 1500);
    });
});

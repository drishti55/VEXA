(function() {
    'use strict';

    // Array of motivational quotes (at least 15)
    const quotes = [
        { text: "The only way to do great work is to love what you do.", author: "Steve Jobs" },
        { text: "The future belongs to those who believe in the beauty of their dreams.", author: "Eleanor Roosevelt" },
        { text: "It does not matter how slowly you go as long as you do not stop.", author: "Confucius" },
        { text: "Believe you can and you're halfway there.", author: "Theodore Roosevelt" },
        { text: "Your time is limited, don't waste it living someone else's life.", author: "Steve Jobs" },
        { text: "The harder you work for something, the greater you’ll feel when you achieve it.", author: "Unknown" },
        { text: "Dream it. Wish it. Do it.", author: "Unknown" },
        { text: "Don’t stop when you’re tired. Stop when you’re done.", author: "Marilyn Monroe" },
        { text: "Little things make big days.", author: "Unknown" },
        { text: "It’s going to be hard, but it’s worth it.", author: "Unknown" },
        { text: "Don’t wait for opportunity. Create it.", author: "Unknown" },
        { text: "Sometimes we’re tested not to show our weaknesses, but to discover our strengths.", author: "Unknown" },
        { text: "The key to success is to focus on goals, not obstacles.", author: "Unknown" },
        { text: "Dream big and dare to fail.", author: "Norman Vaughan" },
        { text: "You are never too old to set another goal or to dream a new dream.", author: "C.S. Lewis" }
    ];

    /**
     * Returns a random index from the quotes array that is not equal to `exclude`.
     * If the array has only one element, that index (0) is returned regardless of `exclude`.
     * @param {number|null|undefined} exclude Index to avoid.
     * @returns {number}
     */
    function getRandomIndex(exclude) {
        const len = quotes.length;
        if (len === 0) {
            return -1;
        }
        if (len === 1) {
            return 0;
        }
        let idx;
        do {
            idx = Math.floor(Math.random() * len);
        } while (exclude != null && idx === exclude);
        return idx;
    }

    /**
     * Renders the quote at the given index into the #quote element.
     * @param {number} index
     */
    function renderQuote(index) {
        if (quoteEl) {
            const q = quotes[index];
            const formatted = `“${q.text}” — ${q.author}`;
            quoteEl.textContent = formatted;
            // store current index for later use
            currentIndex = index;
        }
    }

    /**
     * Shows the toast element for 2 seconds.
     */
    function showToast() {
        if (!toastEl) return;
        toastEl.removeAttribute('hidden');
        toastEl.classList.add('show'); // styles.css keeps #toast at opacity 0 without .show
        // Ensure any previous timeout is cleared
        if (toastTimeout) clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => {
            toastEl.classList.remove('show');
            toastEl.setAttribute('hidden', '');
        }, 2000);
    }

    // Variables that will hold DOM references and state
    let quoteEl = null;
    let newQuoteBtn = null;
    let copyQuoteBtn = null;
    let toastEl = null;
    let toastTimeout = null;
    let currentIndex = -1;

    document.addEventListener('DOMContentLoaded', () => {
        try {
            quoteEl = document.getElementById('quote');
            newQuoteBtn = document.getElementById('new-quote');
            copyQuoteBtn = document.getElementById('copy-quote');
            toastEl = document.getElementById('toast');

            if (!quoteEl || !newQuoteBtn || !copyQuoteBtn || !toastEl) {
                console.warn('Required DOM elements are missing. Script initialization aborted.');
                return;
            }

            // Initial quote
            const initialIdx = getRandomIndex(null);
            renderQuote(initialIdx);

            // New quote handler
            newQuoteBtn.addEventListener('click', () => {
                try {
                    const newIdx = getRandomIndex(currentIndex);
                    renderQuote(newIdx);
                } catch (e) {
                    console.error('Error generating new quote:', e);
                }
            });

            // Copy quote handler
            copyQuoteBtn.addEventListener('click', async () => {
                try {
                    const q = quotes[currentIndex];
                    if (!q) return;
                    const formatted = `“${q.text}” — ${q.author}`;
                    // Try modern Clipboard API first
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        try {
                            await navigator.clipboard.writeText(formatted);
                            showToast();
                            return;
                        } catch (err) {
                            // fall back to legacy method
                        }
                    }
                    // Legacy fallback using a temporary textarea
                    const textarea = document.createElement('textarea');
                    textarea.value = formatted;
                    // Move off-screen
                    textarea.style.position = 'fixed';
                    textarea.style.left = '-9999px';
                    document.body.appendChild(textarea);
                    textarea.select();
                    const successful = document.execCommand('copy');
                    document.body.removeChild(textarea);
                    if (successful) {
                        showToast();
                    } else {
                        alert('Failed to copy quote.');
                    }
                } catch (err) {
                    console.error('Copy failed:', err);
                    alert('Failed to copy quote.');
                }
            });
        } catch (err) {
            console.error('Initialization error:', err);
        }
    });
})();

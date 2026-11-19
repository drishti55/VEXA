# Random Quote Generator

A simple responsive web page that displays a random motivational quote, allows the user to fetch a new quote, and copy the current quote to the clipboard.

## Features
- Random quote selection (no immediate repeats)
- Copy‑to‑clipboard with fallback for older browsers
- Toast notification after copying
- Fully responsive layout (buttons stack below 600 px)
- Keyboard accessible and ARIA‑enhanced

## Project Structure
```
index.html   – page markup
styles.css   – styling (Flexbox, media query)
script.js    – quote logic and UI interactions
README.md    – this file
package.json – optional npm scripts (no build step required)
```

## How to Run
1. Open `index.html` in any modern browser (Chrome, Firefox, Safari, Edge).
2. The page loads with an initial quote.
3. Click **New Quote** to see a different quote.
4. Click **Copy** to copy the quote to the clipboard; a toast will appear for 2 seconds.
5. Use **Tab** to navigate to the buttons and press **Enter** or **Space** to activate them.

## Manual Tests
- Verify a quote is visible on load.
- Ensure two consecutive "New Quote" clicks never show the same text.
- After clicking **Copy**, paste elsewhere to confirm the exact quote was copied.
- Confirm the toast appears for at least 2 seconds and then disappears.
- Resize the browser window:
  - ≥ 600 px – buttons are side‑by‑side and centered.
  - < 600 px – buttons stack vertically with a margin of ≥ 8 px.
- Navigate with the keyboard; all interactive elements should be reachable.
- Check the console for errors (there should be none).

## Build / Minify (Optional)
The assets are already tiny (< 100 KB). If you wish to minify them, you can run a tool of your choice (e.g., `uglifyjs` for JS, `csso` for CSS) and replace the files.

## Known Limitations
- Clipboard API requires a user gesture; the fallback uses a temporary textarea which works in most older browsers.
- The random selection guard works only when there are at least two quotes.

---

*Generated on $(date)*
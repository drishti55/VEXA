# Responsive Digital Clock

## Purpose
This project demonstrates a simple, responsive digital clock web page that displays the current time, date, and day of the week. The clock updates every second using vanilla HTML, CSS, and JavaScript.

## File Structure
- `index.html` – The main HTML file containing the structure and placeholders for the clock.
- `styles.css` – CSS file that styles the clock and ensures responsiveness across common screen widths (320 px, 768 px, 1920 px).
- `script.js` – JavaScript that fetches the local time, formats it, and updates the DOM every second.
- `README.md` – This documentation file.

## How to Run
1. Clone or download the repository.
2. Open `index.html` in any modern web browser (Chrome, Firefox, Safari, Edge).
3. The clock will automatically start and update every second.

## Assumptions
- The page uses the client’s local time via the JavaScript `Date` object.
- No external libraries or frameworks are required.
- The project targets modern browsers that support ES6 features such as `const`, `let`, and arrow functions.

## Testing
- Verify that the displayed time matches the system clock within ±1 second.
- Confirm that the date is in `YYYY‑MM‑DD` format and the weekday is the full English name.
- Resize the browser window to 320 px, 768 px, and 1920 px to ensure the layout remains readable.
- Check the browser console for any JavaScript errors.

Enjoy the clock!
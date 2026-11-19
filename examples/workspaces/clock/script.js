// script.js
function pad(num) {
  return num.toString().padStart(2, '0');
}

function updateClock() {
  const now = new Date();
  const hours = pad(now.getHours());
  const minutes = pad(now.getMinutes());
  const seconds = pad(now.getSeconds());
  const timeString = `${hours}:${minutes}:${seconds}`;

  const year = now.getFullYear();
  const month = pad(now.getMonth() + 1);
  const dayOfMonth = pad(now.getDate());
  const dateString = `${year}-${month}-${dayOfMonth}`;

  const weekdays = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const weekdayName = weekdays[now.getDay()];

  document.getElementById('time').textContent = timeString;
  document.getElementById('date').textContent = dateString;
  document.getElementById('day').textContent = weekdayName;
}

document.addEventListener('DOMContentLoaded', () => {
  updateClock();
  setInterval(updateClock, 1000);
});

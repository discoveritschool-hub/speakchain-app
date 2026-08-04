// Cache only the static application shell. Authenticated API responses and
// learner data are deliberately never cached in the browser.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  });
}

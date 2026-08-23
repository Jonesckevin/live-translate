/* Live Translate - PWA bootstrap.
 * Registers the service worker after the page loads. Kept external so it
 * works under the app's Content-Security-Policy (script-src 'self').
 */
(function () {
  if (!('serviceWorker' in navigator)) return;

  window.addEventListener('load', function () {
    navigator.serviceWorker
      .register('/sw.js')
      .then(function (reg) {
        console.log('Service worker registered', reg.scope);
      })
      .catch(function (err) {
        console.error('Service worker registration failed:', err);
      });
  });
})();

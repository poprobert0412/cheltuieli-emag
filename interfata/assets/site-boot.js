/* site-boot.js — rulează în <head>, înainte de prima pictare: marchează că JavaScript există și aplică tema salvată.
 * Primește: localStorage, cheia 'emag-tema' (aceeași ca în site-theme.js și în raportul generat).
 * Dă înapoi: clasa `js` pe <html> (fără ea, CSS-ul ascunde controalele care au nevoie de script) și, dacă omul a ales
 * o temă, atributul data-theme, ca pagina să nu clipească în tema greșită. E fișier separat, nu script inline,
 * ca politica de conținut din index.html (script-src 'self') să nu aibă nicio excepție.
 * Nu face nimic altceva: comutatorul de temă, meniul și restul pornesc din site.js, după încărcarea paginii.
 */
(function (root) {
  'use strict';

  var doc = root.document.documentElement;
  var STORAGE_KEY = 'emag-tema';

  doc.classList.add('js');
  try {
    var saved = root.localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') doc.setAttribute('data-theme', saved);
  } catch (e) { /* fără stocare (fereastră privată, date blocate): rămâne tema automată */ }
})(window);

/* site-theme.js — comutatorul de temă: automată, luminoasă, întunecată.
 * Primește: butonul #theme-toggle și valoarea salvată (localStorage, cheia 'emag-tema', ca raportul generat).
 * Dă înapoi: nimic; setează data-theme pe <html>, textul butonului (din el vine și numele lui accesibil, fără
 * aria-label care se schimbă și se anunță a doua oară) și culoarea barei browserului (meta theme-color).
 * Cu tema automată, atributul lipsește și decide prefers-color-scheme.
 * Stocarea poate lipsi (fereastră privată, site data blocate): tot ce atinge localStorage e în try/catch.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var STORAGE_KEY = 'emag-tema';
  var MODES = ['auto', 'light', 'dark'];
  var NAMES = { auto: 'automată', light: 'luminoasă', dark: 'întunecată' };

  var button = null;
  var label = null;
  var metaLight = null;
  var metaDark = null;
  var original = null; // culorile din HTML, pentru revenirea la tema automată

  /** Tema salvată sau 'auto' dacă lipsește, e invalidă ori stocarea e blocată. */
  function readSaved() {
    try {
      var value = root.localStorage.getItem(STORAGE_KEY);
      return MODES.indexOf(value) >= 0 ? value : 'auto';
    } catch (e) {
      return 'auto';
    }
  }

  /** Salvează tema; fără stocare, alegerea ține doar cât pagina e deschisă. */
  function save(mode) {
    try { root.localStorage.setItem(STORAGE_KEY, mode); } catch (e) { /* ignorat intenționat */ }
  }

  /** Culoarea barei browserului: la tema forțată ambele meta-uri iau culoarea ei, la automată revin cele din HTML. */
  function updateThemeColor(mode) {
    if (!metaLight || !metaDark || !original) return;
    if (mode === 'auto') {
      metaLight.setAttribute('content', original.light);
      metaDark.setAttribute('content', original.dark);
    } else {
      var color = mode === 'dark' ? original.dark : original.light;
      metaLight.setAttribute('content', color);
      metaDark.setAttribute('content', color);
    }
  }

  /** Aplică tema pe pagină și în buton. */
  function apply(mode) {
    var html = root.document.documentElement;
    if (mode === 'auto') html.removeAttribute('data-theme');
    else html.setAttribute('data-theme', mode);
    button.setAttribute('data-mode', mode);
    label.textContent = 'Temă: ' + NAMES[mode];
    updateThemeColor(mode);
  }

  /** Pornește comutatorul: citește tema salvată și leagă butonul (ciclu auto -> luminoasă -> întunecată). */
  function init() {
    button = root.document.getElementById('theme-toggle');
    label = root.document.getElementById('theme-label');
    if (!button || !label) return;
    metaLight = root.document.querySelector('meta[name="theme-color"][media*="light"]');
    metaDark = root.document.querySelector('meta[name="theme-color"][media*="dark"]');
    if (metaLight && metaDark) original = { light: metaLight.getAttribute('content'), dark: metaDark.getAttribute('content') };

    var current = readSaved();
    apply(current);
    button.addEventListener('click', function () {
      current = MODES[(MODES.indexOf(current) + 1) % MODES.length];
      apply(current);
      save(current);
      Site.dom.announce('Temă: ' + NAMES[current]);
    });
  }

  Site.theme = { init: init };
})(window);

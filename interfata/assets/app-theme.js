/* app-theme.js — tema paginii aplicației: automată, luminoasă, întunecată.
 * Primește: butonul #theme-toggle, eticheta #theme-label și valoarea salvată în localStorage, cheia 'emag-tema'
 * (aceeași cheie ca site-ul explicativ și raportul generat: tema aleasă într-un loc se vede în toate trei).
 * Dă înapoi: nimic; setează data-theme pe <html> (la tema automată atributul lipsește și decide prefers-color-scheme),
 * textul butonului și culoarea barei browserului (meta theme-color).
 * Rulează în <head>, înainte de prima pictare, ca pagina să nu clipească în tema greșită; butonul se leagă după încărcare.
 * Pune și clasa `js` pe <html>: fără ea (JavaScript oprit) CSS-ul nu ascunde nimic din ce s-ar citi și așa.
 * Stocarea poate lipsi (fereastră privată, date blocate): tot ce atinge localStorage e în try/catch.
 * Ce NU face: nu ține minte nimic altceva în localStorage; cheia secretă a aplicației nu ajunge niciodată acolo.
 */
(function (root) {
  'use strict';

  const STORAGE_KEY = 'emag-tema';
  const MODES = ['auto', 'light', 'dark'];
  const NAMES = { auto: 'automată', light: 'luminoasă', dark: 'întunecată' };

  let button = null;
  let label = null;
  let metaLight = null;
  let metaDark = null;
  let original = null; // culorile din HTML, pentru revenirea la tema automată

  /** Tema salvată sau 'auto' dacă lipsește, e invalidă ori stocarea e blocată. */
  function readSaved() {
    try {
      const value = root.localStorage.getItem(STORAGE_KEY);
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
      const color = mode === 'dark' ? original.dark : original.light;
      metaLight.setAttribute('content', color);
      metaDark.setAttribute('content', color);
    }
  }

  /** Pune tema pe <html>; butonul (dacă există deja) își actualizează starea și textul. */
  function apply(mode) {
    const html = root.document.documentElement;
    if (mode === 'auto') html.removeAttribute('data-theme');
    else html.setAttribute('data-theme', mode);
    if (button && label) {
      button.setAttribute('data-mode', mode);
      label.textContent = 'Temă: ' + NAMES[mode]; // din textul butonului vine și numele lui accesibil
    }
    updateThemeColor(mode);
  }

  /** Leagă butonul (ciclu automată -> luminoasă -> întunecată) după ce pagina e încărcată. */
  function init() {
    button = root.document.getElementById('theme-toggle');
    label = root.document.getElementById('theme-label');
    if (!button || !label) return;
    metaLight = root.document.querySelector('meta[name="theme-color"][media*="light"]');
    metaDark = root.document.querySelector('meta[name="theme-color"][media*="dark"]');
    if (metaLight && metaDark) original = { light: metaLight.getAttribute('content'), dark: metaDark.getAttribute('content') };

    let current = readSaved();
    apply(current);
    button.addEventListener('click', function () {
      current = MODES[(MODES.indexOf(current) + 1) % MODES.length];
      apply(current);
      save(current);
      if (root.App && root.App.dom) root.App.dom.announce('Temă: ' + NAMES[current]);
    });
  }

  root.document.documentElement.classList.add('js');
  const saved = readSaved();
  if (saved !== 'auto') root.document.documentElement.setAttribute('data-theme', saved);
  root.document.addEventListener('DOMContentLoaded', init);
})(window);

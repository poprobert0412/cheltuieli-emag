/* app-screens.js — arată UN ecran din cele zece și are grijă de focus, titlul filei și anunțul pentru cititoarele de ecran.
 * Primește: schimbările de ecran de la App.state. Dă înapoi, ca window.App.screens: init(), refreshTitle().
 * Fiecare ecran e o <section data-screen="..."> din aplicatie.html; aici doar se ascund cele care nu sunt de acum
 * (atributul hidden) și se pune data-current-screen pe <html>, ca CSS-ul să poată lărgi pagina pentru raport și să ascundă
 * FAQ-ul și subsolul cât pagina încă verifică aplicația (altfel ar sări în jos când apare ecranul de start).
 * Focusul se mută pe titlul noului ecran doar când omul era în ecranul care dispare (sau nicăieri); dacă citea FAQ-ul,
 * nu i-l furăm: schimbarea se anunță în zona live. La prima afișare a ecranului de start, focusul merge pe butonul mare,
 * doar dacă nu s-a atins nimic până atunci.
 * Ce NU face: nu desenează conținutul ecranelor (fiecare modul app-*.js își desenează ecranul lui).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const TITLE_SUFFIX = ' · Cheltuieli eMAG';
  const DEFAULT_TITLE = 'Cheltuieli eMAG · aplicația locală';

  let main = null;
  let sections = {};
  let current = null;
  let resolvedOnce = false; // a trecut deja de ecranul „loading”?

  /** Titlul (h2) al unui ecran: elementul cu tabindex="-1" din interiorul lui. */
  function headingOf(section) {
    return section ? section.querySelector('[tabindex="-1"]') : null;
  }

  /** Titlul filei din titlul ecranului vizibil, ca fila din fundal să spună ce se întâmplă. */
  function refreshTitle() {
    const heading = headingOf(sections[current]);
    root.document.title = heading && heading.textContent ? heading.textContent + TITLE_SUFFIX : DEFAULT_TITLE;
  }

  /** Arată ecranul `screen`; `previous` e ecranul de dinainte (null la pornire). */
  function show(screen, previous) {
    const active = root.document.activeElement;
    const leaving = previous ? sections[previous] : null;
    const focusWasInsideLeaving = !!leaving && leaving.contains(active);
    const focusWasNowhere = !active || active === root.document.body || active === main;

    Object.keys(sections).forEach(function (name) { sections[name].hidden = name !== screen; });
    root.document.documentElement.setAttribute('data-current-screen', screen);
    current = screen;
    refreshTitle();

    if (screen === 'loading') return;
    const heading = headingOf(sections[screen]);
    if (!resolvedOnce) {
      resolvedOnce = true;
      const start = App.dom.byId('btn-start');
      if (screen === 'ready' && focusWasNowhere && start) start.focus({ preventScroll: true });
      return;
    }
    if (heading && (focusWasInsideLeaving || focusWasNowhere)) heading.focus();
    if (heading) App.dom.announce(heading.textContent);
  }

  /** Găsește ecranele și se abonează la schimbările de stare. */
  function init() {
    main = App.dom.byId('continut');
    sections = {};
    Array.prototype.forEach.call(App.dom.byId('screens').querySelectorAll('[data-screen]'), function (section) {
      sections[section.getAttribute('data-screen')] = section;
    });
    App.state.subscribe(function (now, before) {
      if (now.screen !== before.screen) show(now.screen, before.screen);
    });
    show(App.state.get().screen, null);
  }

  App.screens = { init: init, refreshTitle: refreshTitle };
})(window);

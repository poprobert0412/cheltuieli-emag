/* site-nav.js — meniul de pe mobil și scrollspy-ul din cuprins, cu secțiunea activă în adresă.
 * Primește: <header> cu #menu-toggle, #site-nav și linkurile spre secțiuni (#id).
 * Dă înapoi: nimic; marchează linkul activ cu aria-current și ține adresa (hash) în pas cu secțiunea
 * vizibilă, fără să rescrie o adresă care descrie deja o stare din interiorul secțiunii (adnotare, întrebare).
 * Nu desenează conținut și nu știe ce conține fiecare secțiune.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  var DESKTOP_QUERY = '(min-width: 1100px)'; // de la această lățime cuprinsul e bara laterală fixă
  var PROBE_FRACTION = 0.3; // linia imaginară (din înălțimea ferestrei) care decide secțiunea activă
  var SETTLE_MS = 500; // cât așteptăm după încărcare/salt înainte să scriem adresa din derulare
  var FAQ_PREFIX = 'faq-';

  var header = null;
  var toggle = null;
  var links = [];
  var sections = [];
  var ticking = false;
  var syncAfter = 0; // moment (ms) înainte de care derularea NU rescrie adresa
  var activeId = '';

  /** Secțiunea căreia îi aparține o adresă: id-ul ei, sau secțiunea întrebărilor pentru #faq-*. */
  function sectionOfHash(parsed) {
    if (!parsed.token) return 'start';
    if (parsed.token.indexOf(FAQ_PREFIX) === 0) return 'intrebari';
    return sections.some(function (s) { return s.id === parsed.token; }) ? parsed.token : '';
  }

  /** Marchează linkul secțiunii active (aria-current) și îl aduce în vedere în bara laterală, dacă aceasta derulează. */
  function markActive(id) {
    if (id === activeId) return;
    activeId = id;
    links.forEach(function (link) {
      var on = link.getAttribute('href') === '#' + id;
      if (on) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
      if (on && header.scrollHeight > header.clientHeight && root.matchMedia(DESKTOP_QUERY).matches) {
        link.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  /** Secțiunea aflată sub linia de probă; la capătul paginii, ultima. Citește pozițiile într-un singur pas. */
  function findActive() {
    var atBottom = root.innerHeight + root.scrollY >= doc.documentElement.scrollHeight - 4;
    if (atBottom) return sections[sections.length - 1].id;
    var probe = root.innerHeight * PROBE_FRACTION;
    var found = sections[0].id;
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].el.getBoundingClientRect().top <= probe) found = sections[i].id;
    }
    return found;
  }

  /** La derulare: actualizează linkul activ și, după ce pagina s-a așezat, adresa. */
  function onScroll() {
    if (ticking) return;
    ticking = true;
    root.requestAnimationFrame(function () {
      ticking = false;
      var id = findActive();
      markActive(id);
      if (Date.now() < syncAfter) return;
      var current = sectionOfHash(Site.state.parse());
      if (current !== id) Site.state.replace(id === 'start' ? '' : id);
    });
  }

  /** Închide meniul de mobil; `restoreFocus` readuce focusul pe buton (la Escape). */
  function closeMenu(restoreFocus) {
    header.removeAttribute('data-open');
    toggle.setAttribute('aria-expanded', 'false');
    if (restoreFocus) toggle.focus();
  }

  /** Leagă butonul de meniu: deschidere/închidere, Escape, clic pe link, clic în afară, trecere la desktop. */
  function initMenu() {
    toggle.addEventListener('click', function () {
      var open = header.getAttribute('data-open') === 'true';
      if (open) closeMenu(false);
      else {
        header.setAttribute('data-open', 'true');
        toggle.setAttribute('aria-expanded', 'true');
      }
    });
    doc.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && header.getAttribute('data-open') === 'true') closeMenu(true);
    });
    // Tab după ultimul link scoate focusul din antet: meniul se închide, altfel focusul ar intra în conținutul acoperit de panou
    // (relatedTarget gol = fereastra a pierdut focusul sau s-a atins un element nefocusabil: meniul rămâne deschis)
    header.addEventListener('focusout', function (event) {
      var next = event.relatedTarget;
      if (header.getAttribute('data-open') === 'true' && next && !header.contains(next)) closeMenu(false);
    });
    doc.addEventListener('click', function (event) {
      if (header.getAttribute('data-open') !== 'true') return;
      var inside = header.contains(event.target);
      if (!inside || event.target.closest('#site-nav a')) closeMenu(false);
    });
    var desktop = root.matchMedia(DESKTOP_QUERY);
    var onChange = function () { if (desktop.matches) closeMenu(false); };
    if (desktop.addEventListener) desktop.addEventListener('change', onChange);
    else if (desktop.addListener) desktop.addListener(onChange);
  }

  /** Pornește meniul și scrollspy-ul. */
  function init() {
    header = doc.getElementById('antet');
    toggle = doc.getElementById('menu-toggle');
    var nav = doc.getElementById('site-nav');
    if (!header || !toggle || !nav) return;
    links = Array.prototype.slice.call(nav.querySelectorAll('a[href^="#"]')).filter(function (a) {
      return a.parentNode.tagName === 'LI';
    });
    sections = links.map(function (a) {
      var id = a.getAttribute('href').slice(1);
      return { id: id, el: doc.getElementById(id) };
    }).filter(function (s) { return s.el; });
    if (!sections.length) return;

    initMenu();
    markActive(findActive());
    root.addEventListener('scroll', onScroll, { passive: true });
    root.addEventListener('resize', onScroll, { passive: true });
    // adresa se rescrie din derulare abia după ce pagina s-a așezat (salt la #hash, restaurarea derulării)
    syncAfter = Date.now() + 1500;
    root.addEventListener('load', function () { syncAfter = Date.now() + SETTLE_MS; });
    root.addEventListener('hashchange', function () { syncAfter = Date.now() + SETTLE_MS; markActive(findActive()); });
    ['wheel', 'touchstart', 'keydown'].forEach(function (name) {
      root.addEventListener(name, function () { syncAfter = 0; }, { passive: true, once: true });
    });
  }

  Site.nav = { init: init, sectionOfHash: sectionOfHash };
})(window);

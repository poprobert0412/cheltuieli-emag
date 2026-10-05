/* app-dom.js — construiește noduri DOM și anunță schimbările către cititoarele de ecran.
 * Primește: nume de tag, atribute, copii. Dă înapoi: noduri DOM; se expune ca window.App.dom.
 * Textul intră DOAR ca nod text (textContent), niciodată prin innerHTML: nume de produse și mesaje vin din afara paginii.
 * Stilul (`style`, ca obiect) se pune prin CSSOM, nu ca atribut: așa merge și sub politica de conținut strictă (style-src 'self').
 * Ce NU face: nu știe de ecrane, stări sau API; e folosit de toate celelalte fișiere app-*.js.
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const ANNOUNCE_DELAY_MS = 40; // pauza dintre golirea și umplerea zonei live, ca același text să fie citit din nou
  let pendingAnnounce = null;

  /** Adaugă copiii (noduri, text, numere, liste imbricate) la `parent`; ignoră null/false/undefined. */
  function appendKids(parent, kids) {
    kids.forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      if (Array.isArray(kid)) appendKids(parent, kid);
      else parent.appendChild(kid.nodeType ? kid : root.document.createTextNode(String(kid)));
    });
  }

  /** Aplică atributele: `class`, `style` (obiect, prin CSSOM), `on<eveniment>` (handler), booleene (true = prezent), restul ca text. */
  function applyAttrs(el, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (key) {
      const value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === 'class') el.className = value;
      else if (key === 'style') Object.keys(value).forEach(function (prop) { el.style.setProperty(prop, value[prop]); });
      else if (key.slice(0, 2) === 'on' && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? '' : String(value));
    });
  }

  /** Creează un element HTML: h('p', {class: 'x'}, 'text', altNod). */
  function h(tag, attrs) {
    const el = root.document.createElement(tag);
    applyAttrs(el, attrs);
    appendKids(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }

  /** Golește un nod și îl întoarce. */
  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  /** Elementul cu id-ul dat sau null (scurtătură, ca restul fișierelor să rămână lizibile). */
  function byId(id) {
    return root.document.getElementById(id);
  }

  /** Anunță `message` în zona live politicoasă (#app-live); o golește întâi, ca același text să fie citit și a doua oară. */
  function announce(message) {
    const live = byId('app-live');
    if (!live) return;
    if (pendingAnnounce !== null) root.clearTimeout(pendingAnnounce);
    live.textContent = '';
    pendingAnnounce = root.setTimeout(function () {
      live.textContent = message;
      pendingAnnounce = null;
    }, ANNOUNCE_DELAY_MS);
  }

  /** True dacă utilizatorul a cerut mișcare redusă. */
  function prefersReducedMotion() {
    return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  App.dom = { h: h, clear: clear, byId: byId, announce: announce, prefersReducedMotion: prefersReducedMotion };
})(window);

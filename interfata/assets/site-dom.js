/* site-dom.js — construiește noduri DOM și anunță schimbările către cititoarele de ecran.
 * Primește: nume de tag, atribute, copii. Dă înapoi: noduri DOM; se expune ca window.Site.dom.
 * Textul intră DOAR ca nod text, niciodată prin innerHTML: numele din analiza.json sunt date neîncrezute.
 * Stilul (`style`) se pune prin CSSOM, nu ca atribut: așa merge și sub un CSP strict (style-src 'self').
 * Nu știe de secțiuni, date, teme sau stări; e folosit de toate celelalte fișiere site-*.js.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var ANNOUNCE_DELAY_MS = 40; // pauza dintre golirea și umplerea zonei live, ca același text să fie citit din nou

  /** Adaugă copiii (noduri, text, numere, liste imbricate) la `parent`; ignoră null/false/undefined. */
  function appendKids(parent, kids) {
    for (var i = 0; i < kids.length; i++) {
      var kid = kids[i];
      if (kid == null || kid === false) continue;
      if (Array.isArray(kid)) appendKids(parent, kid);
      else parent.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
  }

  /** Aplică atributele: `class`, `on<eveniment>` (handler), booleene (true = prezent), restul ca text. */
  function applyAttrs(el, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value == null || value === false) return;
      if (key === 'class') el.className = value;
      else if (key === 'style') el.style.cssText = String(value);
      else if (key.slice(0, 2) === 'on' && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? '' : String(value));
    });
  }

  /** Creează un element HTML: h('p', {class: 'x'}, 'text', altNod). */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    applyAttrs(el, attrs);
    appendKids(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }

  /** Creează un element SVG (spațiul de nume corect), cu aceleași reguli ca h(). */
  function svg(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    applyAttrs(el, attrs);
    appendKids(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }

  /** Golește un nod și îl întoarce. */
  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  var BRAND = /(www\.)?(eMAG(\.ro|\.bg|\.hu)?|emag\.(ro|bg|hu))/g; // numele de brand: nu se traduce automat

  /** Text simplu cu numele de brand (eMAG, emag.ro) învelit în <span translate="no">. */
  function brandText(text) {
    var frag = document.createDocumentFragment();
    var str = String(text);
    var last = 0;
    str.replace(BRAND, function (match, _w, _x, _y, _z, offset) {
      if (offset > last) frag.appendChild(document.createTextNode(str.slice(last, offset)));
      frag.appendChild(h('span', { translate: 'no' }, match));
      last = offset + match.length;
      return match;
    });
    if (last < str.length) frag.appendChild(document.createTextNode(str.slice(last)));
    return frag;
  }

  /**
   * Text cu cod inline: bucățile dintre `…` devin <code translate="no">, iar numele de brand
   * primește translate="no". Întoarce un DocumentFragment; nu interpretează HTML.
   */
  function richText(text) {
    var frag = document.createDocumentFragment();
    String(text).split('`').forEach(function (part, index) {
      if (part === '') return;
      frag.appendChild(index % 2 === 1 ? h('code', { translate: 'no' }, part) : brandText(part));
    });
    return frag;
  }

  /** Anunță `message` în zona live politicoasă a paginii (#site-live). */
  function announce(message) {
    var live = document.getElementById('site-live');
    if (!live) return;
    live.textContent = '';
    root.setTimeout(function () { live.textContent = message; }, ANNOUNCE_DELAY_MS);
  }

  /** True dacă utilizatorul a cerut mișcare redusă (animațiile sunt dezactivate). */
  function prefersReducedMotion() {
    return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  Site.dom = { h: h, svg: svg, clear: clear, brandText: brandText, richText: richText, announce: announce, prefersReducedMotion: prefersReducedMotion };
})(window);

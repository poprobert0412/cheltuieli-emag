// Transformă o pagină HTML într-o listă de linii de text (portul lui emag_spend/html_lines.py; BeautifulSoup + lxml devin DOMParser).
// Primește: HTML (text). Dă înapoi: lista de linii (htmlToLines), fără spații duble și fără linii goale, și lista numelor de produs (extractProductNames). O linie nouă apare doar la limitele elementelor de tip bloc (div, p, li, titluri, linkuri, butoane, <br>);
// elementele inline (span, sup, small) se lipesc, deci „222” + „,98” + „Lei” devine „222,98 Lei”. Nu interpretează conținutul (nu știe de comenzi): asta fac parserele.
// Rulează doar unde există DOMParser (pagina extensiei, browserul de test). DOMParser nu execută scripturi și nu încarcă resurse; HTML-ul paginii eMAG e tratat ca date, niciodată inserat în pagină.
import { PY_SPACE, pyStrip } from './python_compat.js';

const SKIP_TAGS = new Set(['script', 'style', 'noscript', 'template', 'svg', 'head']);
const BLOCK_TAGS = new Set([
  'div', 'p', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'tr', 'td', 'th', 'table', 'section', 'article', 'header', 'footer',
  'dl', 'dt', 'dd', 'br', 'button', 'label', 'main', 'nav', 'aside',
  'form', 'a',
]);
// Elementele ale căror texte BeautifulSoup le păstrează în clase speciale (script, style, template, rt, rp): textul lor nu intră în get_text() al unui element obișnuit.
const STRING_CONTAINER_TAGS = new Set(['script', 'style', 'template', 'rt', 'rp']);
// \s din Python (spațiile Unicode ale lui Python, nu cele ale lui JavaScript): serii de spații devin un singur spațiu.
const SPACES = new RegExp(`[${PY_SPACE}]+`, 'gu');
const PRODUCT_ROW_SELECTOR = '.order-items li, ul.product-list li';

// Tipurile de nod din DOM (Node.ELEMENT_NODE etc.), ca numere: modulul nu depinde de obiectul global Node.
const ELEMENT_NODE = 1;
const TEXT_NODE = 3;
const DOCUMENT_NODE = 9;
// Filtrul „doar noduri text” al TreeWalker (NodeFilter.SHOW_TEXT).
const SHOW_TEXT = 0x4;

// Un document fără doctype intră în „quirks mode”, unde selectorii de clasă ignoră majusculele; soupsieve (Python) nu are asemenea mod. Doctype-ul pus în față fixează modul standard,
// deci rezultatul nu depinde de ce doctype are pagina (a doua declarație e ignorată de parser, nu produce text).
const STANDARDS_MODE_DOCTYPE = '<!doctype html>';
// Marca de octeți (BOM): BeautifulSoup o scoate de la începutul unui text înainte de lxml; HTML5 ar păstra-o ca text în pagină.
const BYTE_ORDER_MARK = '\u{feff}';

let parser = null;

/** Documentul HTML al paginii, parsat de browser fără să ruleze nimic din el; un singur DOMParser pentru toate apelurile. Un BOM de la început se scoate, ca în BeautifulSoup. */
function parseHtml(html) {
  parser ??= new DOMParser();
  const withoutMark = html.startsWith(BYTE_ORDER_MARK) ? html.slice(BYTE_ORDER_MARK.length) : html;
  return parser.parseFromString(STANDARDS_MODE_DOCTYPE + withoutMark, 'text/html');
}

/** Numele etichetei cu litere mici (localName: „div” pentru HTML, nume cu majuscule păstrate pentru SVG și MathML); gol pentru ce nu e element. */
function tagName(node) {
  return (node.localName || '').toLowerCase();
}

/** Tipul de container de text al celui mai apropiat element din lanțul de părinți al nodului (script, style, template, rt sau rp), sau null: ca în BeautifulSoup, fiecare text aparține celui mai de jos container. */
function containerKind(node) {
  for (let element = node.parentElement; element !== null; element = element.parentElement) {
    const name = tagName(element);
    if (STRING_CONTAINER_TAGS.has(name)) return name;
  }
  return null;
}

/**
 * Textul unui element, cu spațiile unificate: get_text(" ") din BeautifulSoup lipește TOATE bucățile de text ale descendenților cu câte un spațiu între ele
 * („Foo<b>bar</b>” devine „Foo bar”) și lasă deoparte comentariile și textul din script, style, template, rt, rp (când elementul nu e el însuși unul dintre ele).
 */
function cleanText(element) {
  const wantedKind = STRING_CONTAINER_TAGS.has(tagName(element)) ? tagName(element) : null;
  const strings = [];
  const walker = element.ownerDocument.createTreeWalker(element, SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    if (containerKind(node) === wantedKind) strings.push(node.data);
  }
  return pyStrip(strings.join(' ').replace(SPACES, ' '));
}

/**
 * Câte un nume pentru fiecare rând de produs al comenzii (rând = `li` cu cantitate), în ordinea din pagină. Numele se citește din `.product-description`, nu din poziția liniilor:
 * sub nume pot apărea atribute („garantie electronica”) care nu sunt numele. Un rând „Pachet” (`li.promo-bundle`) primește numele „Pachet: <componenta 1> + <componenta 2>”.
 */
export function extractProductNames(html) {
  const names = [];
  for (const row of parseHtml(html).querySelectorAll(PRODUCT_ROW_SELECTOR)) {
    if (row.querySelector('.product-quantity') === null) continue; // rând imbricat (componentă de pachet): cantitatea e la rândul pachetului
    const parts = [...row.querySelectorAll('.product-description')].map(cleanText).filter((text) => text !== '');
    const heading = row.querySelector('.promo-heading');
    let name = parts.join(' + ');
    if (heading !== null && parts.length > 0) name = `${cleanText(heading)}: ${name}`;
    names.push(name);
  }
  return names;
}

/** Adaugă în `parts` textul nodului și al descendenților lui, cu „\n” la limitele elementelor de tip bloc; comentariile, doctype-ul și elementele din SKIP_TAGS nu produc nimic. */
function walk(node, parts) {
  if (node.nodeType === TEXT_NODE) {
    parts.push(node.data.replace(SPACES, ' '));
    return;
  }
  if (node.nodeType !== ELEMENT_NODE && node.nodeType !== DOCUMENT_NODE) return;
  const name = tagName(node);
  if (SKIP_TAGS.has(name)) return;
  const isBlock = BLOCK_TAGS.has(name);
  if (isBlock) parts.push('\n');
  for (const child of node.childNodes) walk(child, parts);
  if (isBlock) parts.push('\n');
}

/** Liniile de text vizibile din HTML, în ordinea din pagină. */
export function htmlToLines(html) {
  const doc = parseHtml(html);
  const parts = [];
  walk(doc.body ?? doc, parts);
  return parts.join('').split('\n').map((line) => pyStrip(line.replace(SPACES, ' '))).filter((line) => line !== '');
}

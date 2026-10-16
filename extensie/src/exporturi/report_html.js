// Raportul HTML autonom: șablonul-schelet, designul (CSS și JS) și datele analizei, lipite într-un singur text (portul lui emag_spend/report_html.py).
// Primește: textul șablonului, al CSS-ului și al JS-ului de design (sursele unice din templates/ și interfata/assets/, lipite la build) și rezumatul analizei. Dă înapoi: textul raportului, fără să scrie fișiere.
// Raportul e UN SINGUR fișier HTML autonom: designul și datele sunt inline, graficele se desenează în browser, fără internet. Designul însuși stă în dashboard.css / dashboard.js, nu aici și nu în șablon.
// Opțiunile sunt facultative: fără ele păstrează exact ieșirea Python; context:'extension' completează marcajele de context și noscript înaintea designului și a datelor.
// Ce NU face: nu validează rezumatul (o face componenta din browser). ValueError (PyValueError) dacă șablonul sau designul nu se potrivesc.
import { PyValueError, pyJsonDumps } from '../calcul/python_compat.js';

const CSS_PLACEHOLDER = '/*__DASHBOARD_CSS__*/';
const JS_PLACEHOLDER = '/*__DASHBOARD_JS__*/';
const DATA_PLACEHOLDER = '/*__DATE_ANALIZA__*/null';
const OPTIONS_PLACEHOLDER = '/*__REPORT_OPTIONS__*/{}';
const NOSCRIPT_START = '<!--__REPORT_NOSCRIPT__-->';
const NOSCRIPT_END = '<!--__REPORT_NOSCRIPT_END__-->';
// Text aprobat de Robert pe 16.10.2026: extensia nu oferă rezumat.txt, iar JSON-ul se descarcă separat.
const EXTENSION_NOSCRIPT = 'Raportul are nevoie de JavaScript ca să se deseneze. Poți descărca aceleași date din extensie în format JSON.';

// Secvențe care, într-un element de script sau de stil inline, ar putea închide sau deruta parserul HTML. Nu le rescriem în tăcere: designul nostru nu le are, iar dacă apar, cineva trebuie să afle.
const FORBIDDEN_IN_INLINE_JS = ['</script', '<!--'];
const FORBIDDEN_IN_INLINE_CSS = ['</style', '<!--'];

// Rolurile celor trei texte primite, pentru mesajele de eroare: Python numește fișierul (calea lui), aici textele vin gata citite, deci mesajul numește rolul.
const TEMPLATE_ROLE = 'șablonul raportului';
const CSS_ROLE = 'designul CSS';
const JS_ROLE = 'designul JS';

/** Textul ca după `Path.read_text` din Python (mod text): CRLF și CR devin LF, ca raportul să nu depindă de sfârșitul de rând al fișierelor de pe disc. */
function universalNewlines(text) {
  return text.replace(/\r\n?/g, '\n');
}

/** Textul unui fișier de design sau al șablonului; ValueError dacă lipsește (nu e text), ca „fișierul de design … lipsește” din Python. */
function requireText(value, missingMessage) {
  if (typeof value !== 'string') throw new PyValueError(missingMessage);
  return universalNewlines(value);
}

/** Verifică un design inline: refuză conținutul care ar rupe tag-ul în care se lipește (lowercase, ca `str.lower` din Python). */
function checkInlineAsset(text, forbidden, role) {
  const lowered = text.toLowerCase();
  for (const marker of forbidden) {
    if (lowered.includes(marker)) throw new PyValueError(`${role} conține „${marker}” și nu poate fi lipit inline în raport`);
  }
}

/**
 * Înlocuiește `placeholder` (care trebuie să apară exact o dată) cu `value`. Înlocuirea e prin tăiere, nu prin String.replace cu șir:
 * acesta dă înțeles special secvențelor $& $1 $$ din `value`, iar designul (JS, CSS) le poate conține.
 */
function fill(template, placeholder, value) {
  const found = template.split(placeholder).length - 1;
  if (found !== 1) throw new PyValueError(`${TEMPLATE_ROLE} trebuie să conțină ${placeholder} exact o dată (am găsit ${found})`);
  const at = template.indexOf(placeholder);
  return template.slice(0, at) + value + template.slice(at + placeholder.length);
}

/** Înlocuiește fallbackul noscript delimitat explicit; ambele limite trebuie să apară exact o dată și în ordine. */
function extensionNoscript(template) {
  fill(template, NOSCRIPT_START, NOSCRIPT_START);
  fill(template, NOSCRIPT_END, NOSCRIPT_END);
  const start = template.indexOf(NOSCRIPT_START);
  const end = template.indexOf(NOSCRIPT_END);
  if (end <= start) throw new PyValueError(`${TEMPLATE_ROLE}: marcajele REPORT_NOSCRIPT sunt în ordine greșită`);
  return fill(template, template.slice(start, end + NOSCRIPT_END.length), EXTENSION_NOSCRIPT);
}

/**
 * Textul raportului autonom. Fără opțiuni păstrează ordinea și ieșirea Python; contextul extensiei completează întâi marcajele sale explicite.
 * Datele se pun ULTIMELE, deci un marcaj scris într-un nume de produs nu mai are ce înlocui. Sfârșiturile de rând din intrări devin LF.
 */
export function buildReport(template, css, js, summary, options) {
  const templateText = requireText(template, `${TEMPLATE_ROLE} lipsește`);
  const cssText = requireText(css, 'fișierul de design CSS lipsește');
  checkInlineAsset(cssText, FORBIDDEN_IN_INLINE_CSS, CSS_ROLE);
  const jsText = requireText(js, 'fișierul de design JS lipsește');
  checkInlineAsset(jsText, FORBIDDEN_IN_INLINE_JS, JS_ROLE);
  // Toate „<” din date devin cele șase caractere «backslash, u, 0, 0, 3, c» (escape valid în JSON): un nume de produs nu poate închide elementul de script al datelor (cu eticheta lui de închidere)
  // și nici deschide un comentariu HTML urmat de un script, care ar face parserul să ignore închiderea reală. JSON.parse dă înapoi textul original. Separatorii impliciți ai lui json.dumps (", " și ": "), numerele cu fracții ca repr(float) din Python.
  const data = pyJsonDumps(summary, { indent: null, fractions: true }).replaceAll('<', '\\u003c');
  let html = templateText;
  if (options && options.context === 'extension') {
    const reportOptions = { context: 'extension' };
    if (typeof options.appName === 'string') reportOptions.appName = options.appName;
    html = fill(html, OPTIONS_PLACEHOLDER, JSON.stringify(reportOptions).replaceAll('<', '\\u003c'));
    html = extensionNoscript(html);
  }
  html = fill(html, CSS_PLACEHOLDER, cssText);
  html = fill(html, JS_PLACEHOLDER, jsText);
  return fill(html, DATA_PLACEHOLDER, data);
}

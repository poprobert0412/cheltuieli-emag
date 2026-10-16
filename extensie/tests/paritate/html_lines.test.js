// Paritatea lui html_lines.js (DOMParser, în browser) față de emag_spend/html_lines.py (BeautifulSoup + lxml): liniile și numele de produse pentru fiecare pagină din html.json.
// Pornește un browser cu playwright-core (canalul din EXT_TEST_CHANNEL: implicit „msedge” pe Windows, „chromium” în rest), fără rețea reală (--host-resolver-rules=MAP * ~NOTFOUND): pagina de test și modulele
// se servesc prin context.route de pe https://paritate.test/, sub CSP-ul paginilor unei extensii MV3 (script-src 'self'), iar tot ce pleacă în altă parte e un eșec al testului.
// Se compară EXACT: o diferență apare cu pagina, prima linie diferită și cele două variante. Singurele diferențe lxml / HTML5 permise sunt cele acceptate
// de Robert (E12), scrise în ACCEPTED_DIFFERENCES cu valorile exacte. Clarificare aprobată pe 16.10.2026: profilul runtime libxml2 stabilește dacă diferența trebuie să existe.
// Ce NU face: nu testează parserele de comenzi (parsere.test.js) și nu folosește un server local (nicio poartă deschisă pe calculator).
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright-core';

import { loadFixture } from '../fixturi.js';

const EXTENSION_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
// Canalul browserului: Edge pe Windows (Chromium-ul descărcat de Playwright nu pornește din aplicația Claude), Chromium în CI.
const BROWSER_CHANNEL = process.env.EXT_TEST_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium');
// Nicio adresă nu se rezolvă: o cerere scăpată de context.route eșuează la rezolvarea numelui, nu ajunge pe internet.
const NO_NETWORK_ARGS = ['--host-resolver-rules=MAP * ~NOTFOUND'];
// Gazda falsă: servită doar de context.route. „.test” e rezervat (RFC 6761), deci nu poate fi un site real.
const ORIGIN = 'https://paritate.test';
const TEST_PAGE_PATH = '/tests/browser/html_lines.html';
const CASES_PATH = '/cazuri.json';
// Singurele foldere (relative la extensie/) din care se servesc fișiere: pagina de test și modulele de calcul pe care le importă.
const SERVED_FOLDERS = ['tests/browser', 'src/calcul'];
const MIME_TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8' };
// CSP-ul implicit al paginilor de extensie din Manifest V3: aceleași constrângeri ca în producție (fără script inline, fără eval).
const EXTENSION_PAGE_CSP = "script-src 'self'; object-src 'self'";
// Cât așteptăm pornirea browserului și rularea tuturor paginilor (câteva secunde pe un calculator obișnuit; cu rezervă pentru unul lent) și cât de des întrebăm pagina dacă a terminat.
const BROWSER_TIMEOUT_MS = 120_000;
const POLL_INTERVAL_MS = 100;
// Praguri împotriva unui test golit în tăcere: câte pagini trebuie să aibă fixtura și câte cazuri de mână trebuie să rămână aici.
const MIN_PAGES = 90;
const MIN_EXTRA_CASES = 40;
// libxml2 documentează tokenizerul HTML5 începând cu 2.14: https://gnome.pages.gitlab.gnome.org/libxml2/html/HTMLparser_8h.html.
// Limita este a bibliotecii runtime (nu a OS-ului, a versiunii lxml sau a bibliotecii de compilare).
const HTML5_LIBXML_MINOR = 14;
// E12 acceptă exact perechea legacy din 14.10.2026. Clarificarea pentru libxml2 >= 2.14, aprobată de Robert pe 16.10.2026,
// cere textul decodat exact în ambele parsere. Dispariția diferenței legacy, textul schimbat chiar dacă e egal și orice altă diferență rămân erori.
const ACCEPTED_DIFFERENCES = new Map([
  ['capcana_entitate_fara_punct_virgula', { linii: {
    legacy: { python: ['a &amp b &lt c'], browser: ['a & b < c'] },
    html5: { python: ['a & b < c'], browser: ['a & b < c'] },
  } }],
]);

const htmlFixture = loadFixture('html');
const fixturePages = htmlFixture.pagini;

/** Profilul tokenizerului real: metadata este obligatorie, versiunile necunoscute nu sunt ghicite din ieșiri. */
function parserProfile(parser) {
  const versionValid = (version, length) => Array.isArray(version) && version.length === length
    && version.every((part) => Number.isSafeInteger(part) && part >= 0) && version[0] > 0;
  if (!parser || parser.backend !== 'lxml' || !versionValid(parser.lxml_version, 4)
    || !versionValid(parser.libxml_runtime, 3) || !versionValid(parser.libxml_compiled, 3)
    || parser.libxml_runtime[0] !== 2) {
    throw new Error(`metadata parser lipsă, invalidă sau nesuportată: ${JSON.stringify(parser)}`);
  }
  return parser.libxml_runtime[1] >= HTML5_LIBXML_MINOR ? 'html5' : 'legacy';
}

/** Textul abaterii de la perechea exactă a profilului; null dacă e conformă, undefined pentru câmpurile fără excepție. */
function acceptedDifferenceProblem(name, field, expected, got, parser) {
  const profiles = ACCEPTED_DIFFERENCES.get(name)?.[field];
  if (!profiles) return undefined; // câmpul nu are diferență acceptată: se compară normal
  const profile = parserProfile(parser);
  const accepted = profiles[profile];
  if (JSON.stringify(expected) !== JSON.stringify(accepted.python) || JSON.stringify(got) !== JSON.stringify(accepted.browser)) {
    return `${name} / ${field}: ieșire schimbată față de profilul ${profile} (E12): Python ${JSON.stringify(expected)}, browserul ${JSON.stringify(got)}; se cere Python ${JSON.stringify(accepted.python)}, browser ${JSON.stringify(accepted.browser)}`;
  }
  return null;
}

// Cazuri scrise de mână, cu ieșirea lui Python (3.13, BeautifulSoup 4.15 + lxml 6.1) la scrierea testului: semantica lui get_text(" ") (bucățile de text se lipesc cu spațiu, comentariile și
// script / style / rt / rp nu intră în numele de produs), potrivirea exactă a claselor indiferent de doctype (DOMParser fără doctype intră în quirks mode, unde selectorii ignoră majusculele),
// scoaterea BOM-ului și un șir de stricăciuni de HTML des întâlnite la care lxml și parserul HTML5 construiesc aceleași linii.
// Diferențele cunoscute dintre cele două parsere (entități fără punct și virgulă, </br>, <form> în <form>, <noscript> la începutul documentului, <td> în afara unui tabel, text după </html>) NU sunt aici:
// cea din fixtura html.json (entitățile fără punct și virgulă) este verificată prin profilul exact de mai sus, iar restul sunt în raportul agentului.
const EXTRA_CASES = [
  { nume: 'descriere_inline_se_lipesc_cu_spatiu', html: '<ul class="product-list"><li><p class="product-description">Foo<b>bar</b>baz <i> x </i></p><span class="product-quantity">1 buc</span></li></ul>', linii: ['Foobarbaz x', '1 buc'], nume_produse: ['Foo bar baz x'] },
  { nume: 'descriere_cu_br', html: '<ul class="product-list"><li><p class="product-description">A<br>B</p><span class="product-quantity">1 buc</span></li></ul>', linii: ['A', 'B', '1 buc'], nume_produse: ['A B'] },
  { nume: 'descriere_cu_comentariu_intre_texte', html: '<ul class="product-list"><li><p class="product-description">A<!-- c -->B</p><span class="product-quantity">1 buc</span></li></ul>', linii: ['AB', '1 buc'], nume_produse: ['A B'] },
  { nume: 'descriere_cu_script_si_style', html: '<ul class="product-list"><li><p class="product-description">A<script>var z=1</script>B<style>p{}</style>C</p><span class="product-quantity">1 buc</span></li></ul>', linii: ['ABC', '1 buc'], nume_produse: ['A B C'] },
  { nume: 'descriere_cu_ruby', html: '<ul class="product-list"><li><span class="product-description">A<ruby>B<rt>r</rt><rp>(</rp></ruby>C</span><span class="product-quantity">1 buc</span></li></ul>', linii: ['ABr(C1 buc'], nume_produse: ['A B C'] },
  { nume: 'descriere_goala', html: '<ul class="product-list"><li><span class="product-description">   </span><span class="product-quantity">1 buc</span></li></ul>', linii: ['1 buc'], nume_produse: [''] },
  { nume: 'descriere_cu_nbsp_si_entitati', html: '<ul class="product-list"><li><span class="product-description">Ceai &amp; Cafea&nbsp;Test &lt;mare&gt;</span><span class="product-quantity">1 buc</span></li></ul>', linii: ['Ceai & Cafea Test <mare>1 buc'], nume_produse: ['Ceai & Cafea Test <mare>'] },
  { nume: 'doua_descrieri_se_unesc_cu_plus', html: '<ul class="product-list"><li><p class="product-description">Unu</p><p class="product-description">Doi</p><span class="product-quantity">1 buc</span></li></ul>', linii: ['Unu', 'Doi', '1 buc'], nume_produse: ['Unu + Doi'] },
  { nume: 'descriere_goala_intre_doua', html: '<ul class="product-list"><li><p class="product-description">A</p><p class="product-description"> </p><p class="product-description">B</p><span class="product-quantity">1 buc</span></li></ul>', linii: ['A', 'B', '1 buc'], nume_produse: ['A + B'] },
  { nume: 'pachet_cu_descriere_goala', html: '<ul class="product-list"><li class="promo-bundle"><span class="promo-heading">Pachet</span><span class="product-quantity">1 buc</span><span class="product-description"> </span></li></ul>', linii: ['Pachet1 buc'], nume_produse: [''] },
  { nume: 'descriere_este_chiar_un_rt', html: '<ul class="product-list"><li><rt class="product-description">A<b>B</b></rt><span class="product-quantity">1 buc</span></li></ul>', linii: ['AB1 buc'], nume_produse: ['A B'] },
  { nume: 'descriere_este_chiar_un_script', html: '<ul class="product-list"><li><script class="product-description">var z = 1;</script><span class="product-quantity">1 buc</span></li></ul>', linii: ['1 buc'], nume_produse: ['var z = 1;'] },
  { nume: 'feff_la_marginea_liniei_nu_se_taie', html: '<p>a</p><p>\u{feff}b\u{feff}</p><p> c\u{feff} </p>', linii: ['a', '\u{feff}b\u{feff}', 'c\u{feff}'], nume_produse: [] },
  { nume: 'feff_in_descriere_nu_se_taie', html: '<ul class="product-list"><li><span class="product-description">\u{feff}A\u{feff}</span><span class="product-quantity">1 buc</span></li></ul>', linii: ['\u{feff}A\u{feff}1 buc'], nume_produse: ['\u{feff}A\u{feff}'] },
  { nume: 'pachet_fara_descrieri', html: '<ul class="product-list"><li class="promo-bundle"><span class="promo-heading">Pachet</span><span class="product-quantity">1 buc</span></li></ul>', linii: ['Pachet1 buc'], nume_produse: [''] },
  { nume: 'pachet_cu_componente', html: '<ul class="product-list"><li class="promo-bundle"><span class="promo-heading">Pachet <b>mare</b></span><span class="product-quantity">1 buc</span><ul><li><p class="product-description">A</p></li><li><p class="product-description">B</p></li></ul></li></ul>', linii: ['Pachet mare1 buc', 'A', 'B'], nume_produse: ['Pachet mare: A + B'] },
  { nume: 'ambele_selectoare_un_singur_rand', html: '<div class="order-items"><ul class="product-list"><li><span class="product-description">A</span><span class="product-quantity">1 buc</span></li></ul></div>', linii: ['A1 buc'], nume_produse: ['A'] },
  { nume: 'rand_in_rand', html: '<ul class="product-list"><li><span class="product-description">A</span><span class="product-quantity">1 buc</span><ul><li><span class="product-description">B</span></li></ul></li></ul>', linii: ['A1 buc', 'B'], nume_produse: ['A + B'] },
  { nume: 'rand_fara_cantitate', html: '<ul class="product-list"><li><span class="product-description">A</span></li></ul>', linii: ['A'], nume_produse: [] },
  { nume: 'clase_cu_majuscule_fara_doctype', html: '<ul class="Product-List"><li><span class="Product-Description">A</span><span class="Product-Quantity">1 buc</span></li></ul>', linii: ['A1 buc'], nume_produse: [] },
  { nume: 'clasa_mixta_fara_doctype', html: '<ul class="product-list"><li><span class="Product-Description">A</span><span class="product-quantity">1 buc</span></li></ul>', linii: ['A1 buc'], nume_produse: [''] },
  { nume: 'clase_cu_majuscule_doctype_html4', html: '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN"><ul class="Product-List"><li><span class="Product-Description">A</span><span class="Product-Quantity">1 buc</span></li></ul>', linii: ['A1 buc'], nume_produse: [] },
  { nume: 'clasa_exacta_doctype_html4', html: '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN"><ul class="product-list"><li><span class="product-description">A</span><span class="product-quantity">1 buc</span></li></ul>', linii: ['A1 buc'], nume_produse: ['A'] },
  { nume: 'bom_la_inceput', html: '\u{feff}<p>a</p><p>b</p>', linii: ['a', 'b'], nume_produse: [] },
  { nume: 'p_in_p', html: '<p>unu<p>doi<p>trei', linii: ['unu', 'doi', 'trei'], nume_produse: [] },
  { nume: 'div_in_p', html: '<p>unu<div>doi</div>trei</p>', linii: ['unu', 'doi', 'trei'], nume_produse: [] },
  { nume: 'div_in_span_in_p', html: '<p><span>unu<div>doi</div>trei</span></p>', linii: ['unu', 'doi', 'trei'], nume_produse: [] },
  { nume: 'formatare_gresita', html: '<b>a<i>b</b>c</i>d', linii: ['abcd'], nume_produse: [] },
  { nume: 'a_in_a', html: '<a href=x>unu<a href=y>doi</a>trei</a>', linii: ['unu', 'doi', 'trei'], nume_produse: [] },
  { nume: 'buton_in_buton', html: '<button>a<button>b</button>c</button>', linii: ['a', 'b', 'c'], nume_produse: [] },
  { nume: 'li_fara_ul', html: '<li>unu<li>doi<li>trei', linii: ['unu', 'doi', 'trei'], nume_produse: [] },
  { nume: 'ul_in_li', html: '<ul><li>unu<ul><li>doi</li></ul>trei</li></ul>', linii: ['unu', 'doi', 'trei'], nume_produse: [] },
  { nume: 'tabel_fara_tbody', html: '<table><tr><td>A</td><td>B</td></tr></table>', linii: ['A', 'B'], nume_produse: [] },
  { nume: 'text_in_tabel', html: '<table>text<tr><td>A</td></tr></table>', linii: ['text', 'A'], nume_produse: [] },
  { nume: 'tabel_in_p', html: '<p>a<table><tr><td>b</td></tr></table>c</p>', linii: ['a', 'b', 'c'], nume_produse: [] },
  { nume: 'titlu_in_p', html: '<p>a<h1>b</h1>c</p>', linii: ['a', 'b', 'c'], nume_produse: [] },
  { nume: 'majuscule_si_atribute_fara_ghilimele', html: '<DIV CLASS=x>A<P TITLE=a>B</P></DIV>', linii: ['A', 'B'], nume_produse: [] },
  { nume: 'atribut_cu_mai_mare', html: '<p title="a>b">c</p><p title=\'x>y\'>d</p>', linii: ['c', 'd'], nume_produse: [] },
  { nume: 'etichete_de_inchidere_in_plus', html: '<p>a</div></span>b</p>', linii: ['ab'], nume_produse: [] },
  { nume: 'comentariu_cu_sfarsit_gresit', html: '<p>a<!-- x --!>b</p>', linii: ['ab'], nume_produse: [] },
  { nume: 'comentariu_neinchis', html: '<p>a<!-- x', linii: ['a'], nume_produse: [] },
  { nume: 'script_neinchis', html: '<p>a</p><script>var x = \'<p>b</p>\'', linii: ['a'], nume_produse: [] },
  { nume: 'style_neinchis', html: '<p>a</p><style>p{}', linii: ['a'], nume_produse: [] },
  { nume: 'titlu_in_body', html: '<p>a</p><title>t</title><p>b</p>', linii: ['a', 't', 'b'], nume_produse: [] },
  { nume: 'doua_body_si_doua_html', html: '<html><p>a</p><html lang=x><body><p>b</p><body><p>c</p>', linii: ['a', 'b', 'c'], nume_produse: [] },
  { nume: 'head_dupa_body', html: '<body><p>a</p><head><title>t</title></head>', linii: ['a', 't'], nume_produse: [] },
  { nume: 'doar_comentariu', html: '<!-- nimic -->', linii: [], nume_produse: [] },
  { nume: 'sfarsituri_de_rand_CR_LF', html: '<p>a\r\nb\rc</p>', linii: ['a b c'], nume_produse: [] },
  { nume: 'input_in_label', html: '<label><input type=checkbox> text</label>', linii: ['text'], nume_produse: [] },
  { nume: 'select_si_textarea', html: '<select><option>unu<option>doi</select><textarea>  unu\n  doi </textarea>x', linii: ['unudoi unu doi x'], nume_produse: [] },
  { nume: 'pre_cu_rand_nou_la_inceput', html: '<pre>\nunu\ndoi</pre>', linii: ['unu doi'], nume_produse: [] },
  { nume: 'svg_si_math', html: '<svg><a><text>t</text></a></svg><math><mi>x</mi><mo>+</mo><mn>1</mn></math><p>vizibil</p>', linii: ['x+1', 'vizibil'], nume_produse: [] },
  { nume: 'elemente_necunoscute_si_image', html: '<foo-bar>a<baz>b</baz></foo-bar>c<image src=x>text', linii: ['abctext'], nume_produse: [] },
  { nume: 'emoji_si_litere_speciale', html: '<p>\u{1f600} emoji \u{df} \u{1e9e} \u{fb01} ș ț</p>', linii: ['\u{1f600} emoji \u{df} \u{1e9e} \u{fb01} ș ț'], nume_produse: [] },
];

/** Prima diferență dintre două liste de text: indexul și cele două valori; null dacă sunt identice. */
function firstDifference(expected, got) {
  const length = Math.max(expected.length, got.length);
  for (let index = 0; index < length; index += 1) {
    if (expected[index] !== got[index]) return { index, expected: expected[index], got: got[index], expectedLength: expected.length, gotLength: got.length };
  }
  return null;
}

/** Textul unei diferențe pentru mesajul de eroare (cu JSON, ca spațiile ciudate și caracterele invizibile să se vadă). */
function describeDifference(name, field, difference) {
  return `${name} / ${field}: la indexul ${difference.index} Python are ${JSON.stringify(difference.expected)}, browserul are ${JSON.stringify(difference.got)} (${difference.expectedLength} față de ${difference.gotLength} elemente)`;
}

/** Compară prin excepția exactă declarată, dacă există, altfel prin egalitatea normală; aceeași cale este folosită de regresii și de browser. */
function comparisonProblem(name, field, expected, got, parser) {
  const accepted = acceptedDifferenceProblem(name, field, expected, got, parser);
  if (accepted !== undefined) return accepted;
  const difference = firstDifference(expected, got);
  return difference ? describeDifference(name, field, difference) : null;
}

/** Răspunsul pentru un fișier de pe https://paritate.test/ (doar din folderele permise), sau 404. */
function fileResponse(pathname) {
  const relative = decodeURIComponent(pathname).replace(/^\/+/, '');
  const absolute = path.resolve(EXTENSION_ROOT, relative);
  const allowed = SERVED_FOLDERS.some((folder) => absolute.startsWith(path.resolve(EXTENSION_ROOT, folder) + path.sep));
  if (!allowed || !existsSync(absolute) || !statSync(absolute).isFile() || !(path.extname(absolute) in MIME_TYPES)) {
    return { status: 404, contentType: 'text/plain; charset=utf-8', body: `nu există: ${pathname}` };
  }
  const headers = path.extname(absolute) === '.html' ? { 'content-security-policy': EXTENSION_PAGE_CSP } : {};
  return { status: 200, contentType: MIME_TYPES[path.extname(absolute)], headers, body: readFileSync(absolute) };
}

describe('html_lines.js în browser (DOMParser) față de html_lines.py (BeautifulSoup + lxml)', () => {
  let browser;
  let results;
  const problems = []; // erori de consolă, excepții în pagină, răspunsuri de eroare, cereri în afara gazdei false
  const allCases = [...fixturePages, ...EXTRA_CASES].map(({ nume, html }) => ({ nume, html })); // rezultatele vin în aceeași ordine: întâi paginile din fixtură, apoi cazurile de mână

  /** Diferențele (ca text) dintre ce a dat Python pentru `cases` și rezultatele din browser care încep la `offset`; listă goală dacă sunt identice. */
  function differencesFor(cases, offset) {
    const differences = [];
    cases.forEach((expected, index) => {
      const got = results[offset + index];
      assert.equal(got.nume, expected.nume, 'ordinea rezultatelor');
      if (got.eroare !== undefined) {
        differences.push(`${expected.nume}: excepție în browser: ${got.eroare}`);
        return;
      }
      for (const field of ['linii', 'nume_produse']) {
        const problem = comparisonProblem(expected.nume, field, expected[field], got[field], htmlFixture.parser);
        if (problem) differences.push(problem);
      }
    });
    return differences;
  }

  before(async () => {
    browser = await chromium.launch({ channel: BROWSER_CHANNEL, headless: true, args: NO_NETWORK_ARGS });
    const context = await browser.newContext();
    await context.route('**/*', (route) => { // plasa de siguranță: orice cerere neacoperită mai jos e blocată și notată
      problems.push(`cerere în afara gazdei false: ${route.request().method()} ${route.request().url()}`);
      return route.abort('blockedbyclient');
    });
    await context.route(`${ORIGIN}/**`, (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === CASES_PATH) return route.fulfill({ status: 200, contentType: MIME_TYPES['.json'], body: JSON.stringify({ pagini: allCases }) });
      const response = fileResponse(url.pathname);
      if (response.status !== 200) problems.push(`răspuns ${response.status} pentru ${url.pathname}`);
      return route.fulfill(response);
    });
    const page = await context.newPage();
    page.on('pageerror', (error) => problems.push(`excepție în pagină: ${error.message}`));
    page.on('console', (message) => { if (message.type() === 'error') problems.push(`eroare de consolă: ${message.text()}`); });
    await page.goto(`${ORIGIN}${TEST_PAGE_PATH}`);
    const deadline = Date.now() + BROWSER_TIMEOUT_MS;
    let state;
    while ((state = await page.evaluate(() => document.documentElement.dataset.stare)) === undefined) { // pagina scrie data-stare când a rulat toate cazurile
      assert.deepEqual(problems, [], 'pagina de test a întâmpinat probleme înainte să termine'); // un modul lipsă sau o eroare de consolă nu așteaptă timpul întreg
      assert.ok(Date.now() < deadline, `pagina de test nu a terminat în ${BROWSER_TIMEOUT_MS} ms`);
      await new Promise((resolve) => { setTimeout(resolve, POLL_INTERVAL_MS); });
    }
    assert.equal(state, 'gata', `pagina de test a dat eroare: ${await page.evaluate(() => window.eroareHtmlLines)}\nprobleme: ${JSON.stringify(problems)}`);
    results = await page.evaluate(() => window.rezultateHtmlLines);
  }, { timeout: BROWSER_TIMEOUT_MS });

  after(async () => {
    await browser?.close();
  });

  test('pagina de test rulează fără erori și fără cereri în afara gazdei false', () => {
    assert.deepEqual(problems, []);
    assert.equal(results.length, allCases.length, 'câte un rezultat pentru fiecare caz');
  });

  test(`fixtura html.json: ${fixturePages.length} pagini, liniile și numele de produse identice cu Python (în afară de diferențele acceptate, E12)`, (t) => {
    assert.ok(fixturePages.length >= MIN_PAGES, `doar ${fixturePages.length} pagini în fixtură`);
    const profile = parserProfile(htmlFixture.parser);
    t.diagnostic(`profil ${profile}; backend ${JSON.stringify(htmlFixture.parser)}`);
    const pageNames = new Set(fixturePages.map((page) => page.nume));
    const unused = [...ACCEPTED_DIFFERENCES.keys()].filter((name) => !pageNames.has(name));
    assert.deepEqual(unused, [], 'diferențe acceptate pentru pagini care nu mai există în fixtură: scoate-le din ACCEPTED_DIFFERENCES');
    const differences = differencesFor(fixturePages, 0);
    assert.deepEqual(differences, [], `${differences.length} diferențe lxml / HTML5:\n${differences.join('\n')}`);
    t.diagnostic(`${fixturePages.length} pagini identice cu Python (${fixturePages.reduce((sum, page) => sum + page.linii.length, 0)} linii, ${fixturePages.reduce((sum, page) => sum + page.nume_produse.length, 0)} nume de produse)`);
  });

  test(`${EXTRA_CASES.length} cazuri scrise de mână (get_text, clase, BOM, HTML stricat des întâlnit), identice cu Python`, (t) => {
    assert.ok(EXTRA_CASES.length >= MIN_EXTRA_CASES, `doar ${EXTRA_CASES.length} cazuri scrise de mână`);
    assert.equal(new Set(EXTRA_CASES.map((c) => c.nume)).size, EXTRA_CASES.length, 'numele cazurilor trebuie să fie unice');
    const differences = differencesFor(EXTRA_CASES, fixturePages.length);
    assert.deepEqual(differences, [], `${differences.length} diferențe:\n${differences.join('\n')}`);
    t.diagnostic(`${EXTRA_CASES.length} cazuri identice cu Python`);
  });
});

describe('profiluri explicite libxml2: regresii pentru clarificarea E12 aprobată pe 16.10.2026', () => {
  // Versiuni inventate pentru profiluri; 2.14.0 este limita tehnică documentată de libxml2, nu versiunea calculatorului sau a CI-ului.
  const legacy = { backend: 'lxml', lxml_version: [9, 0, 0, 0], libxml_runtime: [2, 13, 99], libxml_compiled: [2, 12, 3] };
  const html5 = { ...legacy, libxml_runtime: [2, 14, 0] };
  const name = 'capcana_entitate_fara_punct_virgula';
  const literal = ['a &amp b &lt c'];
  const decoded = ['a & b < c'];

  test('legacy cere exact perechea literal Python / decodat browser', () => {
    assert.equal(comparisonProblem(name, 'linii', literal, decoded, legacy), null);
  });

  test('profilul HTML5 acceptă egalitatea exactă a textului decodat', () => {
    assert.equal(comparisonProblem(name, 'linii', decoded, decoded, html5), null);
  });

  test('dispariția diferenței pe profilul legacy rămâne eroare', () => {
    assert.equal(typeof comparisonProblem(name, 'linii', decoded, decoded, legacy), 'string');
  });

  test('egalitatea pe alt text nu ocolește valorile exacte ale profilului HTML5', () => {
    assert.equal(typeof comparisonProblem(name, 'linii', literal, literal, html5), 'string');
    assert.equal(typeof comparisonProblem(name, 'linii', ['text nou'], ['text nou'], html5), 'string');
  });

  test('orice ieșire nouă a Python-ului sau browserului este refuzată în ambele profiluri', () => {
    for (const [parser, expected] of [[legacy, literal], [html5, decoded]]) {
      assert.equal(typeof comparisonProblem(name, 'linii', [...expected, 'nou'], decoded, parser), 'string');
      assert.equal(typeof comparisonProblem(name, 'linii', expected, [...decoded, 'nou'], parser), 'string');
    }
  });

  test('alte pagini și câmpuri nu primesc excepția E12', () => {
    assert.equal(typeof comparisonProblem('pagina_inventata', 'linii', literal, decoded, html5), 'string');
    assert.equal(typeof comparisonProblem(name, 'nume_produse', literal, decoded, html5), 'string');
    assert.equal(comparisonProblem('pagina_inventata', 'linii', decoded, decoded, html5), null);
  });

  test('metadata lipsă, invalidă sau cu backend necunoscut nu ghicește profilul', () => {
    for (const parser of [undefined, null, {}, { ...legacy, backend: 'altul' }, { ...legacy, libxml_runtime: '2.14.0' },
      { ...legacy, libxml_runtime: [2, 14] }, { ...legacy, libxml_runtime: [2, -1, 0] }, { ...legacy, libxml_runtime: [3, 0, 0] },
      { ...legacy, lxml_version: [] }, { ...legacy, libxml_compiled: null }]) {
      assert.throws(() => comparisonProblem(name, 'linii', literal, decoded, parser), /metadata.*parser/i);
    }
  });

  test('profilul vine din biblioteca runtime, nu din versiunea lxml sau din cea de compilare', () => {
    const runtimeHtml5 = { ...legacy, libxml_runtime: [2, 15, 7] };
    const runtimeLegacy = { ...legacy, libxml_compiled: [2, 15, 7] };
    assert.equal(comparisonProblem(name, 'linii', decoded, decoded, runtimeHtml5), null);
    assert.equal(comparisonProblem(name, 'linii', literal, decoded, runtimeLegacy), null);
  });
});

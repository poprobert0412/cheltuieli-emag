# Extensia Chrome „Cheltuieli eMAG”: plan de implementare

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o extensie Chrome (Manifest V3) care face, în browserul utilizatorului, aceeași analiză ca programul Python, cu cifre identice la ban, verificate automat.

**Architecture:** analiza rulează într-o filă a extensiei (`aplicatie.html`); paginile eMAG se citesc dintr-o filă eMAG de lucru, prin funcții injectate (`chrome.scripting`), iar parsarea și calculul sunt portul 1:1 al modulelor din `emag_spend/`. Un generator Python scrie, pentru aceleași intrări, ieșirile Python; testele JS cer exact aceleași ieșiri.

**Tech Stack:** JavaScript ES modules (fără bundler, fără dependențe la rulare), Manifest V3, Node 24 (`node --test`), `playwright-core` 1.63.0 (doar teste), Python 3.13/3.14 (generatorul de paritate), GitHub Actions.

**Specificația aprobată:** `docs/specificatii/2026-10-13-extensie-chrome.md` (decizii E1–E11, aprobate pe 13.10.2026; E9, numele, la aprobarea textelor). Citește-o întreagă înainte de task.

## Global Constraints

- **Fără commit și fără push.** Robert le cere explicit; la final se face un singur commit pe sesiune. Niciun pas de mai jos nu comite.
- **Fișiere disjuncte:** atingi doar fișierele din secțiunea „Files” a task-ului tău. Recitești un fișier chiar înainte să-l editezi (lucrează mai mulți agenți în același folder).
- **Antet la fiecare fișier** (3–8 rânduri: ce face, ce primește, ce dă înapoi, ce nu e treaba lui) și **comentariu de documentare la fiecare funcție** (1–3 rânduri, cu capcana, dacă există). Comentariile spun de ce, nu cum. Texte în română, cu ș/ț cu virgulă.
- **Caractere:** fără caractere invizibile, fără NBSP literal (scrie `\u00a0`), fără litere cu sedilă (scrie `\u015f`, `\u0163`, `\u015e`, `\u0162` în JS și în Python, inclusiv în corpusurile de test din generator); sfârșit de rând LF. `tests/test_garda_caractere.py` verifică tot ce urcă în depozit.
- **Secvențele `\uXXXX` se verifică după scriere:** unealta de editare a agenților poate transforma un escape în caracterul real (vezi antetul lui `tests/test_garda_caractere.py`). După orice scriere care conține `\u`, verifici octeții (de exemplu cu `cat -A` sau cu Python); dacă s-a transformat, rescrii cu un script Python care construiește backslash-ul cu `chr(92)`.
- **Zero hardcodări din date reale** (CLAUDE.md §4): nume de produse, numere de comandă și sume în teste sunt inventate sau vin din generatorul Python. Pragurile și limitele sunt constante cu nume, cu comentariul care spune de ce acea valoare; cele care există în Python au aceeași valoare și un test de paritate.
- **Un fișier = o treabă; fără `utils.js`, `helpers.js`, `common.js`, `misc.js`, `tools.js`.**
- **Numele în port:** fișierul JS are numele modulului Python (`order_parser.py` devine `extensie/src/calcul/order_parser.js`); funcțiile au numele Python în camelCase (`parse_order` devine `parseOrder`); cheile datelor sunt exact cele din `to_dict` al Python (snake_case, în aceeași ordine a câmpurilor).
- **Reguli de port obligatorii** (`extensie/src/calcul/python_compat.js`, Task 1): `//` și `%` doar prin `floorDiv` / `pyMod`; `round` doar prin `pyRound` / `pyRoundInt`; orice comparare sau sortare de text prin `compareCodePoints` / `sortedBy`; orice `max(..., key=)` prin `maxBy`; orice dicționar Python cu chei venite din date (numere de comandă, nume) devine `Map`, nu obiect; `str.strip()` / `str.split()` fără argument prin `pyStrip` / `pySplit`; clasele regex Python `\s`, `\d`, `\w`, `\b` prin constantele din `python_compat.js`, cu steagul `u`.
- **Manifestul:** permisiuni exact `storage`, `scripting`; `host_permissions` exact `https://www.emag.ro/*`; fără `tabs`, `cookies`, `downloads`, `webRequest`, `<all_urls>`, `content_scripts`, `web_accessible_resources`, `externally_connectable`; CSP implicită.
- **Rețea:** singurul `fetch` din codul extensiei e în `extensie/src/colectare/page_functions.js` (funcția injectată în fila eMAG), doar pe căi relative. Fără `XMLHttpRequest`, `WebSocket`, `eval`, `new Function`, scripturi inline sau externe, `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write` cu date.
- **Testele nu ating rețeaua reală:** orice browser de test pornește cu `--host-resolver-rules=MAP * ~NOTFOUND`; eMAG-ul fals nu folosește redirecționări (Playwright nu interceptează urmarea lor; probat 13.10.2026).
- **Python local:** generatorul rulează cu `.venv\Scripts\python.exe` din rădăcina proiectului (are bs4 și lxml). Pytest NU rulează cu Python-ul de sistem (un pachet `tests` din site-packages umbrește folderul `tests/`): folosește venv-ul curat din scratchpad-ul sesiunii (calea exactă e în brief-ul tău), cu `-m pytest -q -p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1` și `PYTHONUTF8=1`.
- **Browser local pentru e2e:** `msedge` (Chromium-ul descărcat nu pornește din aplicația Claude; Chrome oficial nu încarcă extensii din linia de comandă). În CI: `chromium` (Playwright). Variabila `EXT_TEST_CHANNEL` alege canalul; implicit `msedge` pe Windows, `chromium` în rest.
- **Nu slăbești niciun test existent.** Suita Python întreagă trebuie să rămână verde.
- **Raportul tău final** (în ultimul mesaj): fișierele create/modificate, comenzile rulate cu ieșirea reală (numărul de teste), ce n-a mers și ce ai lăsat intenționat neschimbat.

## Structura fișierelor

```
tests/paritate_export.py                     generatorul Python al fixturilor de paritate (Task 1)
tests/compara_extensie.py                    comparatorul pe date reale, pentru acceptanță (Task 5)
tests/test_garda_extensie.py                 garda extensiei: manifest, rețea, caractere (Task 5)
extensie/
  manifest.json                              sursa unică a versiunii și a permisiunilor (Task 4)
  package.json, package-lock.json            doar dev: playwright-core (Task 1)
  CHANGELOG.md                               (Task 6)
  scripts/ruleaza_python.mjs                 pornește generatorul (Task 1)
  scripts/scrie_tabele_unicode.mjs           scrie src/calcul/unicode_tables.js din fixturi (Task 1)
  scripts/build.mjs, scripts/zip.mjs         construiește dist/ și arhiva (Task 4)
  scripts/iconite.mjs                        generează iconițele din bonul aplicației (Task 4)
  src/settings.js                            oglinda constantelor din emag_spend/settings.py (Task 1)
  src/calcul/                                portul: compat, tabele, regex, difflib și modulele de calcul (Task 1, 2, 3)
  src/exporturi/                                exporturi: csv_export, price_history_csv, report_html (Task 2), descarcare (Task 4)
  src/colectare/                             citirea din eMAG (Task 4)
  src/stocare/                               ultima analiză, jurnalul rulării, lacătul (Task 4)
  src/ecrane/                                controlul ecranelor (Task 4)
  src/aplicatie.html, src/background.js      (Task 4)
  src/iconite/                               PNG-uri generate, comise (Task 4)
  tests/unit/, tests/paritate/, tests/e2e/   testele JS
  build/ (ignorat)                           fixturile generate de Python
  dist/ (ignorat)                            extensia gata de încărcat
```

`dist/` și `build/` sunt deja ignorate de `.gitignore` (regulile `dist/`, `build/` se aplică la orice adâncime). `node_modules/` se adaugă în Task 1.

---

### Task 0: Proba pe contul real (Opus + Robert)

**Stare:** extensia de probă e în `extensie/proba/` și a trecut pe un eMAG fals (logat și nelogat). Robert o rulează pe contul lui și lipește rezultatul.

**Ce decide rezultatul:**
- `pasi.comanda_din_fila_emag.are_comanda_nr = true` confirmă E5. Dacă e `false`: STOP, arhitectura colectării se reface înainte de Task 4.
- `pasi.comanda_direct_din_extensie.are_comanda_nr = false` confirmă că cererile directe nu au sesiunea (așteptat).
- `pasi.lista_comenzi.a_trebuit_fila_activa = true`: în Task 4, fila de lucru se aduce în față cât se citesc listele.
- `ms_pana_la_lista_stabila` dă termenul real al randării; dacă e peste 10 s, Task 4 notează valoarea în comentariul constantei.
- `pasi.retururi.buton_vezi_mai_mult` confirmă selectorul `.js-return-history-view-more`.

- [ ] După rezultat: Opus îl scrie în §11 al specificației și șterge `extensie/proba/` (Robert o scoate și din Chrome).

---

### Task 1 (agentul A): fundația de paritate și stratul comun

**Scop:** generatorul Python al fixturilor, uneltele care fac JS-ul să se comporte ca Python și modulele mici de care depind toate celelalte. După el, agenții B, C și D lucrează în paralel.

**Files:**
- Create: `tests/paritate_export.py`
- Modify: `.gitignore` (o secțiune nouă, „Extensia Chrome”, cu `node_modules/`)
- Create: `extensie/package.json`, `extensie/package-lock.json`
- Create: `extensie/scripts/ruleaza_python.mjs`, `extensie/scripts/scrie_tabele_unicode.mjs`
- Create: `extensie/src/settings.js`
- Create: `extensie/src/calcul/unicode_tables.js` (generat, comis), `python_compat.js`, `python_regex.js`, `sequence_matcher.js`
- Create: `extensie/src/calcul/text_normalize.js`, `proportional_split.js`, `models.js`, `warning_messages.js`, `block_status.js`, `money_ro.js`, `dates_ro.js`, `order_links.js`
- Create: `extensie/tests/fixturi.js` (încărcătorul fixturilor, folosit de toate testele de paritate)
- Create: `extensie/tests/unit/python_compat.test.js`, `python_regex.test.js`, `sequence_matcher.test.js`
- Create: `extensie/tests/paritate/primitive.test.js`, `setari.test.js`, `unicode.test.js`

**Interfaces (Produces, folosite de B, C, D):**

```js
// settings.js — oglinda lui emag_spend/settings.py (aceleași nume, aceleași valori; testul setari.test.js le compară)
export const BASE_URL, ORDER_LIST_FIRST_PAGE_PATH, RETURN_LIST_PATH;
export function orderListPagePath(page) {}      // ORDER_LIST_PAGE_PATH.format(page=...)
export function orderDetailPath(orderId) {}     // ORDER_DETAIL_PATH.format(order_id=...)
export const BIG_PURCHASE_THRESHOLD_LEI, MAX_BIG_PURCHASE_THRESHOLD_LEI, HIGHLIGHT_CATEGORIES;
export const FETCH_CONCURRENCY, FETCH_RETRIES, FETCH_BACKOFF_SECONDS, FETCH_TIMEOUT_MS;
export const LOGIN_WAIT_SECONDS, LOGIN_POLL_SECONDS, LIST_RENDER_TIMEOUT_SECONDS, MAX_LIST_PAGES, MAX_RETURN_LOAD_MORE_CLICKS;

// python_compat.js
export function floorDiv(a, b) {}        // a // b pe întregi
export function pyMod(a, b) {}           // a % b pe întregi (semnul împărțitorului)
export function pyRound(x, ndigits) {}   // round(float, n): jumătatea la par, pe valoarea binară exactă; păstrează -0
export function pyRoundInt(x) {}         // round(float) -> întreg, jumătatea la par
export function compareCodePoints(a, b) {}   // -1/0/1, ordinea textului din Python
export function compareKeys(a, b) {}     // chei-tuplu: numere, text, boolean, liste; tip amestecat = TypeError
export function sortedBy(items, keyFn, { reverse = false } = {}) {}   // sorted(..., key=), stabil
export function maxBy(items, keyFn) {}   // max(..., key=): primul maxim
export function pyStrip(s, chars) {}     // str.strip(), cu sau fără chars
export function pyRstrip(s, chars) {}
export function pySplit(s) {}            // str.split() fără argument
export function pyInt(text) {}           // int() pe cifre zecimale, inclusiv din alte alfabete; altfel ValueError
export function pyJsonDumps(value) {}    // json.dumps(value, ensure_ascii=False, indent=1), octet cu octet
export function pyCsvRow(fields) {}      // un rând csv.writer(delimiter=';'), cu '\r\n'
export const PY_SPACE, PY_DIGIT, PY_WORD, PY_NOT_WORD;   // surse de clase regex (fără paranteze drepte în jur)
export const PY_BOUNDARY;                // sursa lui \b din Python (lookaround pe PY_WORD)

// python_regex.js
export class UnsupportedPattern extends Error {}
export class PyPattern {
  constructor(source, { ignoreCase = false, dotAll = false } = {}) {}
  search(text) {}      // re.search -> PyMatch | null
  match(text) {}       // re.match (ancorat la început)
  fullmatch(text) {}
  findall(text) {}     // ca re.findall: text, sau listă de grupuri
  finditer(text) {}
  sub(repl, text, count = 0) {}
  split(text) {}
}
// PyMatch: group(n | nume), groups(), start(n), end(n)
export function escapePython(text) {}    // re.escape

// sequence_matcher.js — port fidel din difflib (CPython 3.13), isjunk = None, autojunk = true
export class SequenceMatcher {
  constructor(a = '', b = '') {}
  setSeq1(a) {}  setSeq2(b) {}
  ratio() {}  quickRatio() {}  realQuickRatio() {}
  getMatchingBlocks() {}   // [[i, j, n], ...] cu santinela finală
}
export function getCloseMatches(word, possibilities, n = 3, cutoff = 0.6) {}

// text_normalize.js
export function normalizeText(text) {}   // NFKD, fără semne combinate (clasa canonică != 0), spații unice, casefold din tabel

// proportional_split.js
export function splitProportionally(total, weights) {}   // RangeError cu același mesaj ca ValueError-ul din Python

// models.js — forma exactă a lui to_dict; ordinea cheilor = ordinea câmpurilor din dataclass
export function makeItem(name, lineTotalBani, qty) {}
export function makeSellerBlock({ seller, status, status_text, has_storno, items = [], products_total_bani = null,
  vouchers_bani = [], shipping_bani = null, services_bani = [], other_bani = [], paid_bani = null, due_bani = null }) {}
export function makeOrder({ order_id, placed_text, placed_at, header_total_bani, blocks = [], warnings = [] }) {}
export function makeReturnRequest({ return_id, detail_path, order_ids, product_names, steps, refund_bani,
  refund_mode, completed, cancelled }) {}
export function orderFromDict(data) {}   export function returnFromDict(data) {}
export function orderYear(order) {}      // proprietatea Order.year
export class LineOutcome {}              // aceleași câmpuri și aceleași proprietăți (getteri cu numele Python: kept_bani, ...)

// warning_messages.js — toate format_* (formatMissingPaidTotal, ...), constantele KIND_*, PAID_CHECK_*,
// ALL_KINDS și parseOrderWarning(text) -> { kind, text, order_ids, return_id, seller, count, detail, affects_totals }

// block_status.js: DELIVERED, CANCELLED, IN_PROGRESS, PAID_ONLY, UNKNOWN, classifyStatus(text)
// money_ro.js: roAmountToBani, parseFullAmount, findAmount, findLastAmount, parseRefundAmount, formatLei
// dates_ro.js: parseRoDatetime
// order_links.js: ORDER_ID_PATTERN, ORDER_URL_PREFIX, isValidOrderId, orderUrl, returnUrl
```

**Fixturile** (`extensie/build/paritate/`, scrise de `tests/paritate_export.py`; fiecare fișier are `{"schema": 1, ...}`):
- `setari.json`: constantele din `settings.py` folosite de extensie și constantele de modul portate (`FUZZY_MATCH_MIN_RATIO`, `MIN_TRUNCATED_PREFIX`, `PERCENT_DECIMALS`, `MIN_ORDERS_PER_PRODUCT`, `YEARLY_CHART_TOP_CATEGORIES`, `TOP_PRODUCTS_LIMIT`, `TOP_SELLERS_LIMIT`, `UNCATEGORIZED_SAMPLE_LIMIT`, `HIGHLIGHT_ITEMS_LIMIT`, `EXTRA_NAME_CLASH_SUFFIX`, `OTHER_LABEL`, `ORDER_ID_PATTERN`, `ORDER_URL_PREFIX`, `MAX_PRODUCT_NAMES_IN_TEXT`).
- `unicode.json`: `casefold` (fiecare punct de cod la care `ch.casefold() != ch`, cu rezultatul), `combining` (intervalele cu `unicodedata.combining(ch) != 0`), `space` (punctele de cod la care `ch.isspace()`), `word` (intervalele pentru `\w` din `re`), `digit` (intervalele `\d`), `digit_zero` (punctul de cod al lui 0 pentru fiecare bloc de cifre, cu `unicodedata.decimal`), `nfkd` (fiecare punct de cod la care NFKD schimbă ceva, cu rezultatul), `unidata_version`.
- `primitive.json`: cazuri de intrare și ieșire Python pentru `normalize_text` (cel puțin 300 de texte: română cu virgulă și cu sedilă, ß, ẞ, ligaturi, greacă, chirilică, emoji, NBSP, tab, secvențe combinate, CJK), funcțiile din `money_ro`, `parse_ro_datetime`, `split_proportionally` (inclusiv erorile, cu mesajul), `round(x, 1)` și `round(x)` (inclusiv egalitățile 12.25, 0.125, 2.675, 0.5, 1.5, -0.5, -12.25, valori mari), `//` și `%` cu negative, sortări de nume (cu emoji și diacritice), `classify_status`, toate funcțiile `format_*` și `parse_order_warning`, `order_links`, `json.dumps(..., ensure_ascii=False, indent=1)` pe valori cu ghilimele, backslash, control, emoji, liste și obiecte goale, și rânduri CSV (cu `;`, `"`, `\n`, `\r`, spații la margini, formule).
- `regex.json`: pentru fiecare model din `config/categorii.json` și `config/categorii.personal.exemplu.json` (patterns și exclude) și un corpus de cel puțin 300 de nume normalizate (numele din `emag_spend/demo_catalog.py` plus capcane: cuvinte lipite de cifre, cratime, puncte, litere non-latine), indicii numelor potrivite de `re.search`. Plus cazuri pentru expresiile interne ale modulelor portate (aceleași texte, rezultatele `match`/`search`/`sub`/`split`).
- `difflib.json`: cel puțin 2.000 de perechi de nume (scurte, lungi, trunchiate cu `[...]`, peste 200 de caractere ca să pornească „autojunk”), cu `ratio`, `quick_ratio`, `real_quick_ratio`, `get_matching_blocks`; plus apeluri `get_close_matches(word, possibilities, n=1, cutoff=0.88)` cu rezultatul.
- `html.json`, `parsere.json`, `analiza.json`: le folosesc B și C (descriere în Task 2 și Task 3); Task 1 le scrie pe toate trei.

Generatorul rulează cu `PYTHONHASHSEED=0` și se verifică singur: rulat de două ori, cu semințe diferite, scrie aceiași octeți (dovadă că ieșirile nu depind de ordinea seturilor Python). Corpusurile sunt deterministe (fără `random` fără sămânță fixă).

- [ ] **Step 1: `.gitignore` și `package.json`.** Adaugă în `.gitignore`, după secțiunea „Mediul de lucru local”, o secțiune cu comentariu: `# --- Extensia Chrome: pachetele de dezvoltare (se refac cu npm ci) ---` și `node_modules/`. Creează `extensie/package.json`:

```json
{
  "name": "cheltuieli-emag-extensie",
  "private": true,
  "type": "module",
  "engines": { "node": ">=24" },
  "scripts": {
    "paritate:genereaza": "node scripts/ruleaza_python.mjs",
    "tabele:unicode": "node scripts/scrie_tabele_unicode.mjs",
    "test:unit": "node --test \"tests/unit/**/*.test.js\"",
    "test:paritate": "npm run paritate:genereaza && node --test \"tests/paritate/**/*.test.js\"",
    "verify": "npm run test:unit && npm run test:paritate"
  }
}
```

Apoi `npm install --save-dev --save-exact playwright-core@1.63.0` (în `extensie/`) ca să apară lockfile-ul. Task 4 și Task 5 adaugă scripturile `build`, `test:e2e` și le pun în `verify`.

- [ ] **Step 2: `scripts/ruleaza_python.mjs`.** Pornește `python -m tests.paritate_export <cale absolută spre extensie/build/paritate>` din rădăcina proiectului, cu `PYTHONHASHSEED=0`, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`. Python-ul vine din variabila `PYTHON` (antetul o documentează); implicit `.venv\Scripts\python.exe` dacă există, altfel `python3` (Linux, macOS) sau `python` (Windows). Iese cu codul generatorului.

- [ ] **Step 3: generatorul, partea de primitive.** Scrie `tests/paritate_export.py` (antet: ce scrie, unde, de ce; „rulat din extensie/scripts/ruleaza_python.mjs; nu e test pytest”). Funcțiile private construiesc fiecare fișier; `main(folder)` le scrie cu `json.dumps(..., ensure_ascii=False, indent=1, sort_keys=False)`. Corpusurile de text sunt liste literale în fișier sau derivate determinist din `emag_spend/demo_catalog.py`.

- [ ] **Step 4: test de determinism, roșu întâi.** În `extensie/tests/paritate/setari.test.js`, primul test rulează generatorul de două ori în foldere temporare, cu `PYTHONHASHSEED=0` și `PYTHONHASHSEED=12345`, și cere fișiere identice. Rulează: `npm run test:paritate` (așteptat: PASS doar după Step 3).

- [ ] **Step 5: `python_compat.js`, testat roșu-verde.** Scrie întâi `tests/unit/python_compat.test.js` (cazuri scrise de mână, cu valoarea Python notată în comentariu), vezi-l picând, apoi implementarea. Codul pentru funcțiile cu capcane:

```js
/** a // b din Python pe întregi: rotunjire spre minus infinit, nu spre zero. */
export function floorDiv(a, b) {
  if (b === 0) throw new RangeError('împărțire întreagă la zero');
  return Math.floor(a / b);
}

/** a % b din Python: restul are semnul împărțitorului. */
export function pyMod(a, b) {
  return a - b * floorDiv(a, b);
}

/** Ordinea textului din Python: pe puncte de cod (JS compară unități UTF-16 și greșește la emoji). */
export function compareCodePoints(a, b) {
  const left = a[Symbol.iterator]();
  const right = b[Symbol.iterator]();
  for (;;) {
    const x = left.next();
    const y = right.next();
    if (x.done || y.done) return x.done === y.done ? 0 : (x.done ? -1 : 1);
    const cx = x.value.codePointAt(0);
    const cy = y.value.codePointAt(0);
    if (cx !== cy) return cx < cy ? -1 : 1;
  }
}

/** round(x, n) din Python: valoarea binară exactă, rotunjită la n zecimale cu jumătatea la par. */
export function pyRound(x, ndigits = 0) {
  if (!Number.isFinite(x)) return x;
  const { numerator, denominator } = exactRational(x);         // x = numerator / denominator, exact
  const scale = 10n ** BigInt(Math.abs(ndigits));
  const num = ndigits >= 0 ? numerator * scale : numerator;
  const den = ndigits >= 0 ? denominator : denominator * scale;
  let quotient = num / den;                                     // BigInt: trunchiere spre zero
  if ((num % den !== 0n) && (num < 0n)) quotient -= 1n;         // podea
  const twice = 2n * (num - quotient * den);                    // 0 <= rest < den
  if (twice > den || (twice === den && quotient % 2n !== 0n)) quotient += 1n;
  const value = ndigits >= 0 ? Number(`${quotient}e-${ndigits}`) : Number(`${quotient}e${-ndigits}`);
  return value === 0 && (x < 0 || Object.is(x, -0)) ? -0 : value;
}
```

`exactRational(x)` desface numărul cu `DataView` (semn, exponent, mantisă ca BigInt). `pyJsonDumps` scrie obiectele în ordinea cheilor, liste și obiecte goale ca `[]` / `{}`, textul prin `JSON.stringify` (aceleași escape-uri ca Python cu `ensure_ascii=False`), întregii ca `String(n)`; un număr care nu e întreg sigur aruncă `TypeError` (comenzi.json și retururi.json n-au fracții; analiza.json, care are procente, se compară pe structură, nu pe octeți). `pyCsvRow` pune ghilimele doar când câmpul conține `;`, `"`, `\r` sau `\n` (ghilimelele din interior se dublează), transformă `null` în text gol și încheie rândul cu `\r\n`.

- [ ] **Step 6: tabelele Unicode.** `scripts/scrie_tabele_unicode.mjs` citește `build/paritate/unicode.json` și scrie `src/calcul/unicode_tables.js` (antet „GENERAT, nu edita de mână”, versiunea `unidata_version`, intervale compacte). `tests/paritate/unicode.test.js` cere: fișierul comis e identic cu ce ar scrie scriptul acum (prospețime) și, pentru fiecare intrare din `nfkd`, `String.fromCodePoint(cp).normalize('NFKD')` dă exact rezultatul Python (dacă ICU-ul din Node diferă de Python, testul numește punctele de cod și nu se slăbește; raportezi lui Opus).

- [ ] **Step 7: `python_regex.js`.** Traduce sursa unui model Python în sursă JS cu steagul `u`. Suportă exact: litere, `\` + punctuație, `.` (devine `[^\n]`, sau orice caracter cu `dotAll`), `^`, `$` (devine `(?:$|(?=\n$))`), clase `[...]` (cu `\d`, `\s`, `\w` traduse înăuntru), `(?:...)`, `(?P<nume>...)`, `(?P=nume)`, `(?=...)`, `(?!...)`, `|`, cuantificatorii `* + ? {n} {n,} {n,m}` și variantele leneșe, `\b \B \d \D \s \S \w \W`. Orice altceva (`(?i)` și alte steaguri, `(?<=`, `(?<!`, `\A`, `\Z`, referințe numerice `\1`, `(?#`, `(?>`, cuantificatori posesivi) aruncă `UnsupportedPattern` cu numele construcției. `PyPattern` folosește `lastIndex` și steagurile `g`/`y` intern, fără să lase stare între apeluri. Teste: `tests/unit/python_regex.test.js` (traduceri de mână, fiecare construcție refuzată) și `tests/paritate/primitive.test.js` (rezultatele din `regex.json`, toate).

- [ ] **Step 8: `sequence_matcher.js`.** Port linie cu linie din `difflib.SequenceMatcher` (CPython 3.13): `__chain_b` cu „autojunk” (`n >= 200`: elementele care apar de mai mult de `n // 100 + 1` ori devin „populare”), `find_longest_match`, `get_matching_blocks` (cu coada de lucru și unirea blocurilor adiacente), `ratio = 2.0 * M / T`, `quick_ratio`, `real_quick_ratio`. `getCloseMatches` reproduce `heapq.nlargest(n, [(score, x)])`: la scor egal câștigă textul mai mare (după `compareCodePoints`). Test: toate perechile din `difflib.json`, cu egalitate exactă a numerelor.

- [ ] **Step 9: modulele mici.** Portează `text_normalize`, `proportional_split`, `models`, `warning_messages`, `block_status`, `money_ro`, `dates_ro`, `order_links`, fiecare cu testul lui de paritate în `tests/paritate/primitive.test.js` (cazurile din `primitive.json`). Expresiile interne se scriu direct în sintaxă JS, cu `PY_SPACE`/`PY_DIGIT`/`PY_WORD` și steagul `u` (`iu` unde Python are `re.IGNORECASE`). `settings.js` și constantele de modul se compară cu `setari.json`.

- [ ] **Step 10: generatorul, partea de pagini și analiză.** Adaugă în `tests/paritate_export.py` fișierele `html.json`, `parsere.json` și `analiza.json`, cu forma din Task 2 și Task 3 (le scrii tu acum, ca B și C să pornească în paralel).

- [ ] **Step 11: verificare.** Rulează în `extensie/`: `npm run verify` (așteptat: toate testele trec), apoi suita Python întreagă cu venv-ul curat (așteptat: verde; `tests/paritate_export.py` nu e colectat de pytest, nu începe cu `test_`).

---

### Task 2 (agentul B): parsarea paginilor și exporturile

**Scop:** paginile eMAG devin aceleași `Order`/`ReturnRequest` ca în Python, iar exporturile (CSV, raport HTML) aceleași fișiere, la octet.

**Files:**
- Create: `extensie/src/calcul/html_lines.js`, `order_parser.js`, `return_parser.js`
- Create: `extensie/src/exporturi/csv_export.js`, `price_history_csv.js`, `report_html.js`
- Create: `extensie/tests/paritate/parsere.test.js`, `exporturi.test.js`
- Create: `extensie/tests/browser/html_lines.html`, `extensie/tests/browser/html_lines_pagina.js`, `extensie/tests/paritate/html_lines.test.js` (rulează pagina de test în browser)

**Interfaces:**
- Consumes (Task 1): `normalizeText`, `models.js`, `warning_messages.js`, `block_status.js`, `money_ro.js`, `dates_ro.js`, `python_compat.js`, `python_regex.js`, `order_links.js`.
- Produces:

```js
// html_lines.js — rulează doar unde există DOMParser (pagina extensiei, browserul de test)
export function htmlToLines(html) {}            // listă de linii, ca html_to_lines
export function extractProductNames(html) {}    // ca extract_product_names
// order_parser.js
export function parseOrder(orderId, lines, productNames = null) {}   // Order (to_dict); Error cu mesajul ValueError-ului
// return_parser.js
export function parseReturn(detailPath, lines) {}                   // ReturnRequest (to_dict)
// exporturi/csv_export.js
export function textCell(value) {}  export function leiCell(bani) {}
export function linesCsv(lines, thresholdBani) {}                   // textul lui produse.csv, cu BOM (\ufeff) la început
// exporturi/price_history_csv.js
export function priceHistoryCsv(priceHistory) {}                    // textul lui istoric_preturi.csv, cu BOM
// exporturi/report_html.js
export function buildReport(template, css, js, summary) {}          // textul raportului autonom; Error ca ValueError-ul din Python
```

**Fixturile pe care le citește** (scrise de Task 1):
- `html.json`: `[{ "nume", "html", "linii", "nume_produse" }]` din `tests/html_builders.py` (ambele așezări, pachete, atribute sub nume, GRATUIT, vouchere, servicii, alte taxe, storno, bloc anulat cu „Total de plata”, mai mulți vânzători, pagini de retur în toate variantele lui `return_page`) plus HTML-capcană (comentarii, `script`, `style`, `noscript`, `template`, `svg`, entități, `<br>`, inline imbricat, spații ciudate).
- `parsere.json`: `[{ "nume", "tip": "comanda" | "retur", "id_sau_cale", "linii", "nume_produse", "rezultat" | "eroare" }]`.
- `analiza.json`: pentru fiecare scenariu, și `linii_csv`, `istoric_csv` (textul exact al fișierelor scrise de Python) și, la scenariul `scenariu`, `raport_html` (textul exact scris de `write_report` cu șablonul și designul de azi).

- [ ] **Step 1:** testele roșii întâi: `parsere.test.js` (fiecare intrare din `parsere.json`: rezultatul identic, sau aceeași eroare), `exporturi.test.js` (CSV-urile și raportul, la octet).
- [ ] **Step 2:** portează `order_parser.py` și `return_parser.py` linie cu linie (cu regulile din Global Constraints; numele de grupuri `(?P<nume>` devin `(?<nume>`; `re.escape` devine `escapePython`).
- [ ] **Step 3:** `html_lines.js`: același mers prin arbore ca `html_lines.py` (aceleași liste `_SKIP_TAGS`, `_BLOCK_TAGS`, aceleași reguli pentru text, comentarii și doctype), pe `DOMParser`. `tests/browser/html_lines.html` (fără script inline) încarcă modulul și cazurile din `html.json`; `html_lines.test.js` deschide pagina în browserul de test (Playwright, canalul din `EXT_TEST_CHANNEL`, cu `--host-resolver-rules=MAP * ~NOTFOUND`, fișierele servite prin `context.route` de pe o adresă `https://paritate.test/`) și cere egalitate pentru fiecare pagină. Diferențele dintre lxml și parserul HTML5 apărute aici se raportează lui Opus, cu pagina; nu se ascund.
- [ ] **Step 4:** exporturile, cu `pyCsvRow` și `pyJsonDumps`.
- [ ] **Step 5: verificare:** `npm run test:unit` și `npm run test:paritate` verzi; raport cu numărul de cazuri trecute.

---

### Task 3 (agentul C): analiza

**Scop:** aceleași `summary` și aceleași linii de registru ca `spend_analysis.analyze`, pe toate scenariile.

**Files:**
- Create: `extensie/src/calcul/block_payment.js`, `line_ledger.js`, `return_matcher.js`, `refund_modes.js`, `paid_totals.js`, `classifier.js`, `product_key.js`, `price_history.js`, `warning_details.js`, `spend_analysis.js`
- Create: `extensie/tests/paritate/analiza.test.js`, `extensie/tests/unit/classifier.test.js`

**Interfaces:**
- Consumes (Task 1): tot stratul comun; `getCloseMatches` din `sequence_matcher.js`; `PyPattern` din `python_regex.js`.
- Produces:

```js
// classifier.js
export class Classifier {
  constructor(rules, source = 'regulile de categorii') {}   // aceleași validări și mesaje ca în Python
  get categoryNames() {}  get defaultCategory() {}
  classify(productName) {}                                    // [categorie, modelul care a potrivit]
}
// refund_modes.js:  export function loadRefundModes(data, source) {}   // validarea din load_refund_modes, pe obiect
// product_key.js:   export function loadColorWords(data, source) {}    export function makeProductKey(name, colorWords) {}
// warning_details.js: export function loadWarningTexts(data, source) {}  (+ restul funcțiilor publice ale modulului)
// spend_analysis.js
export function analyze(orders, returns, classifier, thresholdBani, generatedAt,
  { highlightCategories = [], warningTexts, colorWords, refundModes }) {}   // { summary, lines }
```

Încărcătoarele primesc obiectul deja citit (în extensie, configurările vin ca module generate la build; în teste, din `config/*.json`) și aruncă `Error` cu același mesaj ca `ValueError`-ul din Python, cu `source` în locul căii.

**Fixtura** `analiza.json`: `[{ "nume", "comenzi", "retururi", "reguli", "prag_bani", "generat_la", "evidentiate", "rezumat", "linii", "linii_csv", "istoric_csv", "comenzi_json", "retururi_json" }]` pentru scenariile: `scenariu` (`tests/scenario.py`, cu regulile lui), `demo` (`demo_data.demo_orders_and_returns()`, cu `config/categorii.json` fără reguli personale), `din_pagini` (comenzile și retururile din `parsere.json`), `capcane` (construit determinist în generator: linii negative „Custom Discount”, nume cu emoji, ß și sedile, egalități la sortare, procente cu jumătate exactă, nume trunchiate „[...]”, retururi potrivite aproximativ, moduri de restituire necunoscute și cu credit, blocuri anulate cu retur, comenzi fără dată). `linii` = registrul după analiză, ca `to_dict` plus proprietățile folosite de CSV.

- [ ] **Step 1:** `analiza.test.js` roșu: pe fiecare scenariu, `analyze(...)` dă `rezumat` identic structural (numerele întregi cu `===`, procentele cu `Object.is`, listele în aceeași ordine) și aceleași linii.
- [ ] **Step 2:** portează modulele în ordinea dependențelor: `block_payment`, `line_ledger`, `refund_modes`, `return_matcher`, `paid_totals`, `classifier`, `product_key`, `price_history`, `warning_details`, `spend_analysis`. Fiecare iterare pe set Python se verifică: dacă ieșirea depinde de ordine, STOP și raport lui Opus (generatorul ar fi nedeterminist).
- [ ] **Step 3:** `classifier.test.js`: fiecare model din `config/categorii.json` trece prin `PyPattern` fără `UnsupportedPattern`; un model cu `(?i)` sau `(?<=` e refuzat cu mesajul care numește categoria (regula pentru reguli noi).
- [ ] **Step 4: verificare:** `npm run test:paritate` verde pe toate scenariile; raport cu cifrele (câte linii, câte avertismente pe scenariu).

---

### Task 4 (agentul D): extensia propriu-zisă

**Scop:** extensia încărcabilă din `dist/`: iconița deschide aplicația, colectarea din fila de lucru, analiza (B și C), raportul, descărcările, ultima analiză, jurnalul.

**Pornește după:** Task 0 (rezultatul probei) și Task 1. Codul care leagă analiza se scrie pe interfețele din Task 2 și 3; testele lui de integrare rulează după ce B și C termină.

**Files:**
- Create: `extensie/manifest.json`, `extensie/src/background.js`, `extensie/src/aplicatie.html`
- Create: `extensie/src/colectare/work_tab.js`, `page_functions.js`, `session_check.js`, `order_list_scraper.js`, `return_list_scraper.js`, `page_fetcher.js`, `emag_collector.js`, `progress.js`, `run_errors.js`
- Create: `extensie/src/stocare/last_analysis.js`, `run_log.js`, `run_lock.js`
- Create: `extensie/src/ecrane/main.js`, `screens.js`, `start_screen.js`, `login_screen.js`, `working_screen.js`, `report_screen.js`, `error_screen.js`
- Create: `extensie/src/exporturi/descarcare.js`
- Create: `extensie/scripts/build.mjs`, `extensie/scripts/zip.mjs`, `extensie/scripts/iconite.mjs`, `extensie/src/iconite/icon-16.png`, `icon-32.png`, `icon-48.png`, `icon-128.png`
- Create: `extensie/tests/unit/colectare.test.js`, `extensie/tests/unit/stocare.test.js`, `extensie/tests/unit/build.test.js`
- Modify: `extensie/package.json` (scriptul `build`, `build` în `verify`)

**Manifestul:**

```json
{
  "manifest_version": 3,
  "name": "Cheltuieli eMAG (neoficial)",
  "description": "Cât ai plătit, de fapt, pe eMAG: citește comenzile și retururile din contul tău și calculează totul în browser. Neafiliat cu eMAG.",
  "version": "0.1.0",
  "minimum_chrome_version": "120",
  "permissions": ["storage", "scripting"],
  "host_permissions": ["https://www.emag.ro/*"],
  "background": { "service_worker": "background.js", "type": "module" },
  "action": { "default_title": "Cheltuieli eMAG", "default_icon": { "16": "iconite/icon-16.png", "32": "iconite/icon-32.png" } },
  "icons": { "16": "iconite/icon-16.png", "32": "iconite/icon-32.png", "48": "iconite/icon-48.png", "128": "iconite/icon-128.png" }
}
```

Numele și descrierea sunt provizorii (E9): textele finale vin din Task 6, după aprobarea lui Robert.

**Interfaces (Produces):**

```js
// colectare/work_tab.js
export async function openWorkTab() {}                     // tab creat cu about:blank, inactiv; așteaptă status „complete”
export async function navigate(tabId, url, timeoutMs) {}   // ascultătorul pus ÎNAINTE de chrome.tabs.update; -> adresa finală ('' dacă e pe o gazdă fără permisiune)
export async function runInTab(tabId, func, args = []) {}  // chrome.scripting.executeScript, world 'ISOLATED'
export async function showTab(tabId) {}  export async function closeTab(tabId) {}
// colectare/page_functions.js — funcții FĂRĂ variabile din afara lor (Chrome le serializează)
export function pageLoginState() {}       // { logat, adresa_de_login } ca browser_session._is_logged_in
export function pageOrderIds() {}         // ca _READ_IDS_JS
export function pageLastPageHint() {}     // ca _LAST_PAGE_JS
export function pageReturnPaths() {}      // ca _LINKS_JS
export function pageLoadMoreState() {}    // { exista, vizibil } pentru .js-return-history-view-more
export function pageClickLoadMore() {}
export async function pageFetch(path, timeoutMs) {}   // { status, finalUrl, html }; singurul fetch din extensie
// colectare/progress.js — aceleași faze ca progress.py
export const PHASE_WAITING_LOGIN, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_ANALYZING;
export class RunCancelled extends Error {}
export class Progress { phase(name, total) {} advance(done, total) {} message(text) {} cancel() {} raiseIfCancelled() {} }
// colectare/session_check.js
export class LoginTimeout extends Error {}
export async function ensureLoggedIn(tabId, progress, { onNeedLogin }) {}
// colectare/page_fetcher.js
export class SessionExpired extends Error {}
export async function fetchEach(tabId, paths, handler, label, progress, log) {}
// colectare/order_list_scraper.js, return_list_scraper.js, emag_collector.js
export async function collectOrderIds(tabId, maxOrders, progress, log) {}
export async function collectReturnPaths(tabId, progress, log) {}
export async function collectAll({ maxOrders = null, progress, log }) {}   // -> { orders, returns }; închide fila de lucru în finally
// colectare/run_errors.js
export const ERROR_CODES;                 // login_timeout, session_expired, work_tab_closed, page_changed, network, busy, storage_full, unexpected
export function classifyError(error) {}   // -> { code, message }; mesajele urmează app_errors.py: ce s-a întâmplat + „Ce faci: …”
// stocare/last_analysis.js — cheia LAST_ANALYSIS_KEY = 'ultima_analiza' în chrome.storage.local
export async function saveLastAnalysis(entry) {}   // entry: { schema: 1, extension_version, created_at, threshold_lei, summary, orders, returns, log_text }
export async function loadLastAnalysis() {}  export async function deleteAllData() {}
// stocare/run_log.js — format „%(asctime)s [%(name)s] %(levelname)s: %(message)s”, ca în Python
export class RunLog { info(module, text) {} warning(module, text) {} error(module, text) {} async flush() {} text() {} }
// stocare/run_lock.js — chrome.storage.session; lacăt vechi = fila care l-a luat nu mai există
export async function acquireRunLock(appTabId) {}  export async function releaseRunLock(appTabId) {}
// exporturi/descarcare.js
export function downloadText(fileName, text, mimeType) {}   // Blob + <a download>, adresa revocată după REVOKE_DELAY_MS
```

**Reguli de colectare** (aceleași valori ca în Python, din `settings.js`): login prin semnele „Comenzile mele” + „Log out”, verificat la `LOGIN_POLL_SECONDS`, cel mult `LOGIN_WAIT_SECONDS`; lista de comenzi citită stabil (două citiri identice la 700 ms, fără scheletele `000000000`, termen `LIST_RENDER_TIMEOUT_SECONDS`), paginare ca `collect_order_ids` (aceleași ramuri de oprire), plafon `MAX_LIST_PAGES`; detaliile câte `FETCH_CONCURRENCY`, `FETCH_RETRIES` încercări, pauză `FETCH_BACKOFF_SECONDS * încercare`, `FETCH_TIMEOUT_MS`; `SessionExpired` când adresa finală conține „login” și calea cerută nu; retururile cu „Vezi mai mult” (15 s pe creștere, plafon `MAX_RETURN_LOAD_MORE_CLICKS`). HTML-ul se parsează imediat (`htmlToLines`, `extractProductNames`, apoi parserul) și se aruncă. Dacă proba a cerut fila activă, `collectAll` o aduce în față cât citește listele și spune asta pe ecran.

**Ecranele** (`aplicatie.html`, fără scripturi inline): `ready`, `login`, `working`, `done`, `error`, `cancelled`, `busy`, în același marcaj și cu aceleași clase ca `interfata/aplicatie.html` (citește-l, împreună cu `app.css` și `app-*.js`, înainte de a scrie). Se încarcă, în ordine: `partajat/app-theme.js` (în `<head>`), `partajat/dashboard.js`, `partajat/app-dom.js`, `partajat/app-format.js`, `partajat/app-threshold.js`, `partajat/demo-data.js`, apoi `ecrane/main.js` ca modul. Ce nu există în aplicația locală (ecranul de login, „Șterge datele”, rândul „Ultima analiză”, ecranul `busy`) se face doar din clasele existente; dacă e nevoie de CSS nou, într-un singur fișier `extensie/src/extensie.css`, cu fiecare regulă comentată. Pragul: `App.threshold.read()`; în bani cu `pyRoundInt(lei * 100)`, ca `run_pipeline.py`. Demo: `window.EMAG_DEMO_DATA` cu `mount(root, data, { demo: true })`; la demo se descarcă doar `raport.html` și `analiza.json`.

**Build** (`scripts/build.mjs`, fără dependențe): golește `dist/`; copiază `manifest.json`, `src/**` (fără teste); copiază în `dist/partajat/` fișierele din `interfata/assets/` (`dashboard.js`, `dashboard.css`, `app.css`, `app-theme.js`, `app-dom.js`, `app-format.js`, `app-threshold.js`, `demo-data.js`); scrie `dist/generat/config.js` (`export default` cu cele patru configurări din `config/*.json`, fără `categorii.personal.json`) și `dist/generat/raport_sursa.js` (`export default { template, css, js }` din `templates/raport.html` și designul raportului); copiază `LICENSE`; verifică cu `manifest.json` că fiecare fișier cerut există; `scripts/zip.mjs` face `dist/cheltuieli-emag-<versiune>.zip` cu `zlib.deflateRawSync` și `zlib.crc32` (ZIP standard, fără dependențe). `build.test.js`: arhiva se deschide cu `python -m zipfile -t` și conține exact fișierele din `dist/`.

**Iconițele** (`scripts/iconite.mjs`): randează SVG-ul bonului din `interfata/aplicatie.html` (același desen ca favicon-ul) la 16, 32, 48 și 128 px (la 128: desen de 96 px cu 16 px transparenți pe fiecare parte, cum cere magazinul), cu Playwright și `--host-resolver-rules=MAP * ~NOTFOUND`; PNG-urile se comit.

- [ ] **Step 1:** testele unitare roșii pentru colectare, pe o filă falsă (obiect care imită `runInTab` și `navigate`): login găsit / așteptat / expirat; lista cu schelete, apoi stabilă; paginare cunoscută și necunoscută; dubluri; reîncercări; `SessionExpired` la redirect; „Vezi mai mult” fără creștere; oprire cerută între pagini.
- [ ] **Step 2:** implementează `colectare/` până trec.
- [ ] **Step 3:** `stocare/` cu teste pe un `chrome.storage` fals (salvare, citire, ștergere, lacăt vechi, jurnal scris pe parcurs; o analiză nouă înlocuiește ultima doar la succes).
- [ ] **Step 4:** manifestul, `background.js` (clic pe iconiță: aduce în față fila aplicației salvată în `chrome.storage.session` sau deschide una nouă; la închiderea filei aplicației închide fila de lucru și eliberează lacătul), ecranele, descărcările, build-ul, iconițele.
- [ ] **Step 5: verificare:** `npm run build`; încarcă `dist/` în Edge cu Playwright (headless, rețeaua blocată), deschide aplicația, rulează demo-ul și verifică: fără erori în consolă, raportul are cifra mare, butoanele de descărcare dau fișierele.
- [ ] **Step 6: APROBARE vizuală (STOP).** Capturi luminos și întunecat, la 1280 px și la 400 px, ale fiecărui ecran (cu demo-ul și cu stări simulate), salvate în scratchpad. Opus le arată lui Robert; nimic nu continuă la ecrane până la „da”.

---

### Task 5 (agentul E): e2e, gărzile, CI

**Pornește după:** Task 2, 3 și 4.

**Files:**
- Create: `extensie/tests/e2e/harness.js`, `extensie/tests/e2e/emag_fals.js`, `extensie/tests/e2e/analiza.test.js`, `extensie/tests/e2e/erori.test.js`, `extensie/tests/e2e/stocare.test.js`
- Create: `tests/test_garda_extensie.py`, `tests/compara_extensie.py`
- Modify: `.github/workflows/teste.yml` (jobul `extensie`), `.github/dependabot.yml` (ecosistemul npm pentru `/extensie`), `extensie/package.json` (`test:e2e`, în `verify`)

**Harness:** `launchPersistentContext` cu canalul din `EXT_TEST_CHANNEL`, headless, `--disable-extensions-except` și `--load-extension` spre `dist/`, `--host-resolver-rules=MAP * ~NOTFOUND`; id-ul extensiei din adresa worker-ului; `context.route('**/*')` servește eMAG-ul fals pentru `www.emag.ro` și oprește (cu eșec de test) orice altă gazdă; fiecare cerere văzută se notează, iar testul compară lista cu cea așteptată. eMAG-ul fals (`emag_fals.js`) servește paginile din `html.json`, o listă de comenzi randată cu întârziere (schelete, apoi numere, cu paginare), lista de retururi cu „Vezi mai mult”, iar starea de „nelogat” ca pagină fără „Comenzile mele” / „Log out” la aceeași adresă (fără redirecționări).

- [ ] **Step 1:** `analiza.test.js`: analiza completă pe paginile scenariului `din_pagini` dă exact `rezumat`-ul Python din `analiza.json`, iar descărcările (CSV, `comenzi.json`, `retururi.json`) sunt identice la octet cu ale Python.
- [ ] **Step 2:** `erori.test.js`: nelogat, apoi logat în timpul așteptării (ecranul de login dispare singur); fila de lucru închisă de om; oprire; a doua filă a aplicației (`busy`); pagină schimbată (detaliu fără „Comanda nr.”).
- [ ] **Step 3:** `stocare.test.js`: ultima analiză la redeschidere; „Șterge datele”; o analiză căzută păstrează analiza veche și jurnalul ei.
- [ ] **Step 4:** `tests/test_garda_extensie.py` (Python, cu `tests/garda_js_scan.py`): manifestul are exact permisiunile din Global Constraints; în `extensie/src/**/*.js`: `fetch(` doar în `colectare/page_functions.js`; fără `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`, `eval(`, `new Function`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `chrome.cookies`, `chrome.webRequest`, `chrome.downloads`; adresele din literale doar `https://www.emag.ro`; HTML-ul extensiei fără scripturi inline și fără resurse externe; fișierele din `extensie/` fără caractere invizibile și fără sedile. Fiecare detector are un cod-capcană care trebuie să pice (ca gărzile existente).
- [ ] **Step 5:** `tests/compara_extensie.py`: primește un folder `iesiri/<rulare>` și folderul cu fișierele descărcate din extensie; compară `comenzi.json` și `retururi.json` exact, recalculează analiza Python din comenzile extensiei cu `Classifier.from_file(..., include_personal=False)` și o compară cu `analiza.json` a extensiei; tipărește doar numărători și cheile care diferă, fără nume de produse.
- [ ] **Step 6: CI.** Job nou `extensie` în `teste.yml`: `runs-on: ubuntu-24.04`, `timeout-minutes: 20`, `permissions: contents: read`; pași: `actions/checkout` (același SHA ca jobul pytest, `persist-credentials: false`), `actions/setup-python` (același SHA, 3.13), `pip install --only-binary=:all: -r requirements-dev.txt`, `actions/setup-node` (fixat pe SHA-ul complet al ultimei versiuni, cu `# vX.Y.Z`; acțiune nouă în repo, de anunțat lui Robert), `npm ci`, `npx playwright-core install --with-deps chromium`, `npm run verify` cu `EXT_TEST_CHANNEL=chromium`, arhiva urcată ca artefact cu `retention-days` dintr-o constantă comentată. Dependabot: `package-ecosystem: "npm"`, `directory: "/extensie"`, săptămânal, grupat ca la pip.
- [ ] **Step 7: verificare:** `npm run verify` local (Edge) și suita Python întreagă (cu venv-ul curat) verzi.

---

### Task 6 (agentul F): textele

**Pornește după:** Task 4 (ca textele să descrie ce există). În paralel cu Task 5.

**Files:**
- Create: `docs/CONFIDENTIALITATE-EXTENSIE.md`, `docs/MAGAZIN-EXTENSIE.md`, `extensie/CHANGELOG.md`
- Modify: `README.md` (secțiunea „Extensia Chrome”), `SECURITY.md` (secțiunea extensiei și `tests/test_garda_extensie.py` în lista gărzilor, cum cere `tests/test_site_static.py`), `CONTRIBUTING.md` (cum construiești și testezi extensia), `docs/DECIZII.md` (rândurile E1–E11), `tests/test_decizii.py` (seria `E` în `SERIES`)

- [ ] **Step 1:** politica de confidențialitate (română): ce citește extensia, ce păstrează și unde (§8 din specificație), ce nu atinge, cum se șterge, că autorul nu primește nimic, fraza Limited Use cerută de magazin (în engleză, citată exact din politica Chrome Web Store), contactul (issues pe GitHub). Temeiul fiecărei afirmații într-un comentariu HTML (`<!-- temei: … -->`).
- [ ] **Step 2:** `docs/MAGAZIN-EXTENSIE.md`: variante de nume (E9), descrierea scurtă (cel mult 132 de caractere, numărate în caractere), descrierea lungă, scopul unic, justificarea fiecărei permisiuni, instrucțiunile pentru recenzent (modul demo, fără cont), răspunsurile pentru formularul de date (ce tipuri de date se ating: istoricul comenzilor, sume; nimic transmis), lista capturilor (1280×800, din demo) și a plăcuței de 440×280.
- [ ] **Step 3:** README, SECURITY, CONTRIBUTING; rândurile E1–E11 în DECIZII.md și `SERIES = "DNPE"`; `npm` și `pytest` verzi (testul deciziilor cere ca fiecare Id E citat în cod să aibă rând și invers).
- [ ] **Step 4: APROBARE texte (STOP).** Opus îi arată lui Robert: numele (E9), descrierile, politica, secțiunea din README. Se aplică doar ce aprobă.

---

### Task 7 (Opus): verificarea finală

- [ ] Diff-ul întreg, citit fișier cu fișier, față de specificație și de acest plan.
- [ ] `npm run verify` (Edge local), suita Python întreagă (venv curat), `npm audit --omit=dev --audit-level=high`.
- [ ] Agentul `security-auditor` pe `extensie/` și pe testele noi; constatările se verifică la linia citată înainte de reparație.
- [ ] Capturile finale și raportul pentru Robert: ce merge, ce nu, ce rămâne pentru el (acceptanța pe contul real cu `tests/compara_extensie.py`, contul de dezvoltator, urcarea în magazin), cu ieșirea reală a verificărilor.

---

## Acoperirea specificației (auto-verificare)

| Specificație | Task |
|---|---|
| §1 decizii E1–E11 | E1–E4: arhitectura întregului plan; E5/E6: Task 4 (`work_tab`, `page_functions`); E7: Task 4 (build); E8: Task 4 (manifest); E9: Task 6; E10, E11: Task 7 (ghidul pentru Robert) |
| §2 refolosit / portat / rescris / exclus | Task 1–4 |
| §3 arhitectură, permisiuni, CSP, configurări fără fetch | Task 4 (manifest, build), Task 5 (garda) |
| §4 fluxul | Task 4 |
| §5 erorile | Task 4 (`run_errors`), Task 5 (`erori.test.js`) |
| §6 paritatea | Task 1 (generator, compat), Task 2, Task 3, Task 5 (comparator) |
| §7 interfața și abaterile | Task 4 (ecrane, APROBARE vizuală) |
| §8 stocare, confidențialitate, încadrare | Task 4 (stocare, jurnal), Task 6 (politica) |
| §9 CI, construire, gărzi | Task 1 (`package.json`), Task 4 (build), Task 5 (CI, garda), Task 6 (seria E) |
| §10 testare și acceptanță | Task 2–5, Task 7 |
| §11 proba | Task 0 |
| §12 nu intră în v1 | nimic din plan nu le atinge |
| §13 ordinea | ordinea task-urilor de mai sus |

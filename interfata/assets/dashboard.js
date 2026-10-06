/* =============================================================================
   dashboard.js — componenta „Raport cheltuieli eMAG” (window.EmagDashboard).
   Ce face: validează analiza.json (schema din emag_spend/spend_analysis.py) și
   desenează raportul într-un element: cifra mare (banii plătiți efectiv), lanțul comandat -> plătit,
   categorii, grafic pe ani, achiziții mari, prețuri la același produs, vânzători, control (cu
   avertismentele pe grupe), metodă. Fiecare număr de comandă afișat e un link spre pagina ei de pe eMAG,
   construit doar din numere validate strict (vezi ORDER_URL_PREFIX); linkul se deschide la clic, în filă nouă.
   La fel numele fiecărui produs din tabele (productLink): duce la comanda lui (la un rând cu mai multe comenzi,
   la cea mai recentă), se face albastru la hover și la focus, iar în date de demonstrație rămâne text.
   Ce primește: mount(root, data, options) cu options = { demo?: boolean,
   headingLevel?: 1-5 (implicit 2: titlurile blocurilor sunt h2, cele din ele h3) }.
   Cheile `paid`, `price_history` și `warnings_detail` din analiza.json sunt OPȚIONALE: un fișier vechi, fără ele,
   se desenează ca înainte (la preț de listă, fără blocul de prețuri, cu lista simplă de avertismente).
   Listele și tabelele lungi se desenează câte ROWS_PAGE rânduri („Arată încă”); tabelele cu
   clasa ed-tbl-cards devin liste de carduri pe lățime mică (le comută dashboard.css, nu JavaScript).
   Listele-bară sunt UN singur punct de oprire Tab, cu săgeți între rânduri (rovingFocus).
   Ce dă înapoi: { unmount(), root, ok, errors }. validate(data) -> { ok, errors }.
   Ce NU face: nu citește fișiere, nu face cereri de rețea, nu atinge document.body,
   nu folosește id-uri (două instanțe în aceeași pagină nu se calcă), nu inserează
   NICIODATĂ text din date ca HTML: numele de produse sunt date neîncrezute și
   intră doar prin textContent / createTextNode.
   Gazda trebuie să apeleze unmount() când scoate raportul. Ca plasă de siguranță, o
   instanță a cărei rădăcină a fost scoasă din document (după ce a fost cândva în el) se
   dezmontează singură la următoarea derulare sau redimensionare; pentru a MUTA rădăcina în
   alt loc, apelează mount() din nou acolo.
   Script clasic (nu modul), ca să meargă la dublu-click din file://.
   Design: interfata/assets/dashboard.css (aceeași sursă pentru raport și site).
   ============================================================================= */
(function (global) {
  'use strict';

  const VERSION = '1';
  const NBSP = ' ';
  const MINUS = '−';

  // Câte rânduri desenează o dată orice listă sau tabel lung („Achiziții mari”, produse, vânzători,
  // excluse, evidențiate): un cont vechi poate avea sute de linii, iar un fișier încărcat de mână mii;
  // restul se cer cu „Arată încă”. Python plafonează deja listele la 25/12/80, deci în rapoartele
  // generate butonul apare doar la „Achiziții mari”.
  const ROWS_PAGE = 100;
  // Tabelul de prețuri desenează mai puține rânduri o dată: fiecare e înalt (nume, categorie, micro-diagramă), are un buton de
  // extindere (o oprire Tab) și un SVG; 25 se parcurg ușor, restul vin cu „Arată încă” sau se găsesc cu căutarea.
  const PRICE_ROWS_PAGE = 25;
  // Avertismentele pot fi sute la un cont cu multe probleme; primele 60 se citesc, restul sunt în analiza.json.
  const WARNINGS_SHOWN = 60;
  // Aceeași limită ca UNCATEGORIZED_SAMPLE_LIMIT din spend_analysis.py: acolo se taie lista, aici nu apare mai mult.
  const UNCATEGORIZED_SHOWN = 40;
  // Mesajele de eroare arătate utilizatorului; restul se numără ("… și încă N").
  const ERRORS_SHOWN = 8;
  const PROBLEMS_COLLECTED = 200;
  // Lățimea minimă a unei coloane din graficul pe ani: sub ea barele devin prea subțiri și
  // graficul se lărgește (cardul se derulează orizontal). 22 px lasă 10 ani să încapă pe 360 px;
  // etichetele anilor se răresc singure (vezi yearLabelStep) ca să nu se suprapună.
  const YEAR_SLOT_MIN = 22;
  const CHART_LABEL_CHAR_PX = 6.2; // lățimea medie a unui caracter din etichetele axelor (11 px, cifre tabulare)
  const CHART_DEFAULT_WIDTH = 720;
  // Paleta validată are 7 culori categorice (--ed-s1 … --ed-s7); peste 7 serii culorile se reiau.
  const SERIES_COLORS = 7;
  // Titlurile blocurilor sunt h2 (pagina gazdă are h1); gazda o poate schimba cu options.headingLevel.
  const HEADING_LEVEL_DEFAULT = 2;
  // Cât se așteaptă după ultima literă tastată în căutare înainte să se anunțe numărul de produse găsite:
  // un cititor de ecran ar citi altfel câte un număr la fiecare tastă.
  const ANNOUNCE_DELAY_MS = 500;
  // Micro-diagrama (sparkline) din tabelul de prețuri: mică, ca rândul să rămână de o înălțime cu textul, cu aer
  // pe margini ca marcajele rotunde să nu fie tăiate. Dimensiunile fixe din atribute țin rândurile fără salturi la desenare.
  const SPARK_WIDTH = 96;
  const SPARK_HEIGHT = 28;
  const SPARK_PAD = 4;
  // Un număr de comandă invalid (nu poate deveni link) se afișează ca text, tăiat la atâtea caractere,
  // ca un fișier încărcat de mână să nu poată lărgi tabelele cu un „număr” de mii de caractere.
  const INVALID_ID_SHOWN = 24;

  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const isPlain = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

  /* ---------------------------------------------------------------------------
     Formatare. Intl când browserul are datele ro-RO; altfel formatare manuală cu
     același rezultat. Fiecare formatator se verifică o dată pe un exemplu cunoscut,
     ca un browser fără datele limbii să nu afișeze „1,234.50”.
     --------------------------------------------------------------------------- */
  function groupThousands(digits) { return digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }

  function makeNumberFormatter(fractionDigits) {
    const manual = (n) => {
      const parts = Math.abs(n).toFixed(fractionDigits).split('.');
      return (n < 0 ? '-' : '') + groupThousands(parts[0]) + (parts[1] ? ',' + parts[1] : '');
    };
    try {
      const nf = new Intl.NumberFormat('ro-RO', {
        minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits, useGrouping: 'always',
      });
      const okPositive = nf.format(1234567.25) === (fractionDigits ? '1.234.567,25' : '1.234.567');
      const okNegative = nf.format(-1234) === (fractionDigits ? '-1.234,00' : '-1.234');
      if (okPositive && okNegative) return (n) => nf.format(n);
    } catch (e) { /* fără Intl sau fără useGrouping:'always': formatare manuală */ }
    return manual;
  }
  const fmtMoney = makeNumberFormatter(2);
  const fmtInt = makeNumberFormatter(0);
  const fmtOneDecimal = makeNumberFormatter(1);

  const pad2 = (n) => String(n).padStart(2, '0');
  function makeDateFormatters() {
    const manualDate = (y, m, d) => pad2(d) + '.' + pad2(m) + '.' + y;
    const manualDateTime = (y, m, d, hh, mm) => manualDate(y, m, d) + ', ' + pad2(hh) + ':' + pad2(mm);
    let date = (ts, y, m, d) => manualDate(y, m, d);
    let dateTime = (ts, y, m, d, hh, mm) => manualDateTime(y, m, d, hh, mm);
    try {
      const df = new Intl.DateTimeFormat('ro-RO', { timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric' });
      if (df.format(Date.UTC(2026, 9, 4)) === '04.10.2026') date = (ts) => df.format(ts);
    } catch (e) { /* rămâne manualul */ }
    try {
      const tf = new Intl.DateTimeFormat('ro-RO', {
        timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
      });
      if (tf.format(Date.UTC(2026, 9, 4, 12, 5)) === '04.10.2026, 12:05') dateTime = (ts) => tf.format(ts);
    } catch (e) { /* rămâne manualul */ }
    return { date, dateTime };
  }
  const dateFormatters = makeDateFormatters();
  const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;
  // Sub acest an Intl scrie anul fără zerouri (0099 devine „99”, ambiguu): datele așa rămân text brut.
  const FIRST_FORMATTED_YEAR = 1000;

  /** Momentul UTC al unei date care există în calendar (31 februarie nu există, ora 25 nici), altfel null. */
  function utcTime(y, mo, d, hh, mm) {
    if (hh > 23 || mm > 59) return null;
    const t = new Date(0);
    t.setUTCFullYear(y, mo - 1, d); // spre deosebire de Date.UTC, nu tratează anii 0–99 ca 1900–1999
    t.setUTCHours(hh, mm, 0, 0);
    return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d ? t.getTime() : null;
  }

  /** Data ISO (YYYY-MM-DD, opțional cu oră) în format românesc; text necunoscut sau dată inexistentă rămâne neschimbat. */
  function fmtDate(iso, withTime) {
    if (typeof iso !== 'string' || !iso.trim()) return '';
    const m = ISO_DATE.exec(iso);
    if (!m) return iso;
    const y = +m[1], mo = +m[2], d = +m[3];
    const hasTime = m[4] !== undefined;
    const hh = hasTime ? +m[4] : 0, mm = hasTime ? +m[5] : 0;
    const ts = y < FIRST_FORMATTED_YEAR ? null : utcTime(y, mo, d, hh, mm);
    if (ts === null) return iso; // o dată greșită afișată „frumos” arată credibil: mai bine textul original
    return withTime && hasTime ? dateFormatters.dateTime(ts, y, mo, d, hh, mm) : dateFormatters.date(ts, y, mo, d);
  }

  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : 0);
  const lei = (bani) => fmtMoney(num(bani) / 100) + NBSP + 'Lei';
  const buc = (n) => fmtInt(num(n)) + NBSP + 'buc';
  const pct = (part, whole) => (num(whole) > 0 ? fmtOneDecimal(num(part) / num(whole) * 100) : '0') + NBSP + '%';
  const int = (n) => fmtInt(num(n));

  /** „1 comandă”, „5 comenzi”, „25 de comenzi”: acordul în română, cu spații nedespărțitoare. */
  function count(n, one, many) {
    const k = Math.abs(n) % 100;
    const needsDe = n !== 1 && (k >= 20 || (k === 0 && n !== 0));
    return fmtInt(n) + NBSP + (n === 1 ? one : (needsDe ? 'de' + NBSP : '') + many);
  }

  /** Text pentru căutare: fără diacritice (ș, ț, ă… se descompun în literă + semn combinat), litere mici, spații strânse. */
  function normalizeSearch(text) {
    return String(text).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  /** Împarte „3.130,01” în partea întreagă și zecimale, pentru cifra mare din hero. */
  function splitMoney(bani) {
    const s = fmtMoney(num(bani) / 100);
    const i = s.lastIndexOf(',');
    return i < 0 ? { whole: s, frac: '' } : { whole: s.slice(0, i), frac: s.slice(i) };
  }

  /* ---------------------------------------------------------------------------
     Schema datelor și verificarea ei (mesaje în română, niciodată excepție).
     --------------------------------------------------------------------------- */
  const INT = 'int', STR = 'str', STR_NULL = 'str?', NUM_NULL = 'num?';
  const obj = (fields, optional) => ({ t: 'obj', fields, optional: optional || [] });
  const list = (item) => ({ t: 'list', item });
  const map = (item) => ({ t: 'map', item });
  const ints = (names) => { const f = {}; names.forEach((n) => { f[n] = INT; }); return f; };
  const STATES = ['kept', 'returned', 'cancelled', 'pending', 'unknown'];
  const FUNNEL_PARTS = ['ordered', 'cancelled', 'returned', 'pending', 'unknown', 'kept'];
  const CATEGORY_TOTALS = ['ordered_bani', 'ordered_units', 'kept_bani', 'kept_units', 'returned_bani', 'returned_units',
    'cancelled_bani', 'cancelled_units', 'pending_bani'];
  // Sumele plătite (după partea produsului din reducerile blocului) de pe rânduri; vin împreună cu cheia `paid`.
  const PAID_CATEGORY = ['paid_ordered_bani', 'paid_kept_bani', 'paid_returned_bani', 'paid_cancelled_bani', 'paid_pending_bani'];
  const PAID_YEAR = ['paid_ordered_bani', 'paid_returned_bani', 'paid_cancelled_bani', 'paid_pending_bani', 'paid_unknown_bani', 'paid_fees_bani', 'spent_bani'];
  const YEAR_MATRIX = obj({ years: list(STR), series: list(STR), values: map(map(INT)) });
  // `paid` (emag_spend/paid_totals.py): cifra mare, lanțul în bani plătiți, rândurile care nu sunt produse și reconcilierea.
  const PAID = obj(Object.assign(ints(['spent_bani', 'spent_units', 'list_kept_bani', 'discounts_kept_bani', 'products_kept_bani', 'fees_bani',
    'credit_returns_bani', 'credit_returns_units', 'refund_differences_bani']), {
    extra_rows: list(obj({ key: STR, name: STR, bani: INT })),
    funnel: obj(ints(['ordered_bani', 'cancelled_bani', 'returned_bani', 'pending_bani', 'unknown_bani', 'fees_bani', 'spent_bani',
      'ordered_units', 'cancelled_units', 'returned_units', 'credit_units', 'pending_units', 'unknown_units', 'spent_units'])),
    by_year_category: YEAR_MATRIX,
    reconciliation: obj(ints(['paid_delivered_bani', 'rebuilt_blocks', 'rebuilt_bani', 'cash_refunds_bani', 'estimated_refunds_bani', 'estimated_refunds',
      'credit_returns_delivered_bani', 'credit_returns_added_bani', 'refund_differences_bani', 'spent_bani', 'in_progress_bani', 'paid_only_bani',
      'unknown_bani', 'cancelled_cash_returns_bani', 'cancelled_cash_refunds_shown_bani', 'unattributed_refunds_bani'])),
  }));
  const EXCLUDED_ROW = obj({
    order_id: STR, date: STR, seller: STR, names: list(STR), products_bani: INT, paid_bani: INT, status_text: STR,
  }, ['products_bani', 'status_text']);
  // `price_history` (emag_spend/price_history.py): câmpurile pe care le citește raportul sunt obligatorii, restul opționale.
  const PRICE_PURCHASE = obj({ date: STR_NULL, order_id: STR, seller: STR, name: STR, qty: INT, unit_bani: INT });
  const PRICE_PRODUCT = obj({
    key: STR, name: STR, category: STR, purchases: list(PRICE_PURCHASE), kept_units: INT,
    first_unit_bani: INT, last_unit_bani: INT, min_unit_bani: INT, max_unit_bani: INT,
    last_vs_prev_unit_bani: INT, last_vs_prev_pct: NUM_NULL, last_vs_prev_impact_bani: INT,
    overpaid_vs_min_bani: INT, color_variants: 'bool',
  }, ['category', 'last_vs_prev_pct', 'last_vs_prev_impact_bani', 'color_variants']);
  const PRICE_HISTORY = obj({
    summary: obj(Object.assign(ints(['products', 'purchases', 'units', 'overpaid_vs_min_bani']), {
      last_vs_prev: obj(ints(['cheaper_products', 'pricier_products', 'same_products', 'cheaper_bani', 'pricier_bani'])),
    })),
    products: list(PRICE_PRODUCT),
  });
  // `warnings_detail` (emag_spend/warning_details.py): grupe de avertismente cu rândurile lor; `return_url` e adresa
  // returului, gata construită (sau null), și nu se folosește ca link decât după ce JavaScript o verifică din nou.
  const WARNING_ITEM = obj({
    order_ids: list(STR), return_id: STR_NULL, seller: STR_NULL, status: STR_NULL, placed_at: STR_NULL, text: STR, return_url: STR_NULL,
  }, ['return_id', 'seller', 'status', 'placed_at', 'return_url']);
  const WARNING_GROUP = obj({
    kind: STR, title: STR, explanation: STR, affects_totals: 'bool', what_to_do: STR, count: INT, items: list(WARNING_ITEM),
  }, ['kind']);

  const SCHEMA = obj({
    meta: obj({ generated_at: STR, threshold_bani: INT, first_order: STR_NULL, last_order: STR_NULL, orders: INT, blocks: INT, lines: INT }),
    funnel: obj(ints([].concat(...FUNNEL_PARTS.map((p) => [p + '_bani', p + '_units'])))),
    paid: PAID,
    orders: obj(ints(['total', 'kept_all', 'kept_partial', 'returned_all', 'cancelled_all', 'in_progress', 'paid_only', 'unknown', 'no_items'])),
    by_category: list(obj(Object.assign({ name: STR }, ints(CATEGORY_TOTALS), ints(PAID_CATEGORY)), PAID_CATEGORY)),
    by_year: list(obj(Object.assign({ year: STR }, ints(['orders', 'orders_with_kept', 'ordered_bani', 'kept_bani', 'kept_units', 'returned_bani', 'cancelled_bani']),
      ints(PAID_YEAR)), PAID_YEAR)),
    by_year_category: YEAR_MATRIX,
    top_products: list(obj({ name: STR, category: STR, units: INT, bani: INT, paid_bani: INT, order_id: STR, order_count: INT }, ['paid_bani', 'order_id', 'order_count'])),
    by_seller: list(obj({ seller: STR, units: INT, bani: INT, paid_bani: INT }, ['paid_bani'])),
    big: obj(Object.assign({
      threshold_bani: INT,
      items: list(obj({
        order_id: STR, date: STR, name: STR, seller: STR, category: STR, qty: INT, unit_bani: INT, amount_bani: INT, paid_amount_bani: INT, state: STR,
        returned_from_cancelled: 'bool',
      }, ['returned_from_cancelled', 'paid_amount_bani'])),
    }, ints([].concat(...STATES.map((s) => [s + '_bani', s + '_units']))), ints(STATES.map((s) => s + '_paid_bani'))), STATES.map((s) => s + '_paid_bani')),
    highlights: map(obj({
      totals: obj(Object.assign({ name: STR }, ints(CATEGORY_TOTALS), ints(PAID_CATEGORY)), ['name'].concat(PAID_CATEGORY)),
      items: list(obj({ order_id: STR, date: STR, name: STR, qty: INT, amount_bani: INT, paid_amount_bani: INT, state: STR }, ['paid_amount_bani'])),
      items_total: INT,
    }, ['items_total'])),
    paid_only: list(EXCLUDED_ROW),
    in_progress: list(EXCLUDED_ROW),
    reconciliation: obj(Object.assign(ints([
      'paid_delivered_bani', 'vouchers_delivered_bani', 'shipping_delivered_bani', 'services_delivered_bani',
      'returns_total', 'returns_completed', 'returns_cancelled', 'returns_pending', 'refunds_bani', 'refunds_without_amount',
    ]), { refund_modes: map(INT), header_total_mismatches: list(null), orders_with_storno: list(STR) }),
    ['refunds_without_amount', 'refund_modes', 'header_total_mismatches']),
    returns: obj({ matched_units: INT, matched_from_cancelled_units: INT, unmatched_refund_bani: INT }, ['unmatched_refund_bani']),
    uncategorized: list(obj({ name: STR, units: INT, bani: INT, order_id: STR, order_count: INT }, ['order_id', 'order_count'])),
    uncategorized_count: INT,
    price_history: PRICE_HISTORY,
    warnings: list(STR),
    warnings_detail: list(WARNING_GROUP),
  }, ['paid', 'highlights', 'paid_only', 'in_progress', 'uncategorized', 'uncategorized_count', 'price_history', 'warnings_detail']);
  // Cu `paid`, sumele plătite de pe rânduri devin obligatorii: un fișier amestecat (rânduri fără ele) ar afișa sume de listă drept plătite.
  const PAID_ROWS = obj({
    by_category: list(obj(ints(PAID_CATEGORY))),
    by_year: list(obj(ints(PAID_YEAR))),
    top_products: list(obj({ paid_bani: INT })),
    by_seller: list(obj({ paid_bani: INT })),
    big: obj(Object.assign({ items: list(obj({ paid_amount_bani: INT })) }, ints(STATES.map((s) => s + '_paid_bani')))),
    highlights: map(obj({ totals: obj(ints(PAID_CATEGORY)), items: list(obj({ paid_amount_bani: INT })) })),
  }, ['highlights']);

  const KIND_TEXT = { int: 'un număr întreg', str: 'text', 'str?': 'text sau null', 'num?': 'un număr sau null', bool: 'adevărat sau fals', list: 'o listă', obj: 'un obiect' };
  const FILE_HINT = 'Încarcă fișierul analiza.json din folderul iesiri\\<data>_<ora>\\ al unei rulări.';

  const clip = (s, n) => (s.length > n ? s.slice(0, n) + '…' : s);
  function describeValue(v) {
    if (v === null) return 'null';
    if (Array.isArray(v)) return 'o listă';
    switch (typeof v) {
      case 'string': return 'text („' + clip(v, 24) + '”)';
      case 'number':
        if (!Number.isFinite(v)) return 'un număr invalid';
        if (Number.isSafeInteger(v)) return 'un număr întreg (' + v + ')';
        return Number.isInteger(v) ? 'un număr întreg prea mare (' + v + ')' : 'un număr zecimal (' + v + ')';
      case 'boolean': return 'adevărat sau fals';
      case 'object': return 'un obiect';
      default: return typeof v;
    }
  }
  function matchesKind(v, kind) {
    switch (kind) {
      case INT: return Number.isSafeInteger(v);
      case STR: return typeof v === 'string';
      case STR_NULL: return v === null || typeof v === 'string';
      case NUM_NULL: return v === null || (typeof v === 'number' && Number.isFinite(v));
      case 'bool': return typeof v === 'boolean';
      default: return false;
    }
  }
  const joinPath = (path, key) => (path ? (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) ? path + '.' + key : path + '[' + JSON.stringify(key) + ']') : key);

  function walk(value, spec, path, ctx) {
    if (ctx.problems.length >= PROBLEMS_COLLECTED || spec === null) return;
    if (typeof spec === 'string') {
      if (!matchesKind(value, spec)) ctx.problems.push(path + ' trebuie să fie ' + KIND_TEXT[spec] + ', dar este ' + describeValue(value) + '.');
      return;
    }
    if (spec.t === 'list') {
      if (!Array.isArray(value)) { ctx.problems.push(path + ' trebuie să fie ' + KIND_TEXT.list + ', dar este ' + describeValue(value) + '.'); return; }
      for (let i = 0; i < value.length && ctx.problems.length < PROBLEMS_COLLECTED; i++) walk(value[i], spec.item, path + '[' + i + ']', ctx);
      return;
    }
    if (!isPlain(value)) { ctx.problems.push(path + ' trebuie să fie ' + KIND_TEXT.obj + ', dar este ' + describeValue(value) + '.'); return; }
    if (spec.t === 'map') {
      Object.keys(value).forEach((k) => walk(value[k], spec.item, joinPath(path, k), ctx));
      return;
    }
    Object.keys(spec.fields).forEach((k) => {
      if (!hasOwn(value, k) || value[k] === undefined) {
        if (spec.optional.indexOf(k) < 0) ctx.missing.push(path ? path + '.' + k : k);
        return;
      }
      walk(value[k], spec.fields[k], joinPath(path, k), ctx);
    });
  }

  function missingMessage(missing, topLevel) {
    const shown = missing.slice(0, 6).join(', ') + (missing.length > 6 ? ', …' : '');
    if (topLevel) {
      return 'Fișierul nu pare să fie analiza.json generată de program: ' +
        (missing.length === 1 ? 'lipsește cheia ' : 'lipsesc cheile ') + shown + '. ' + FILE_HINT;
    }
    return (missing.length === 1 ? 'Lipsește cheia ' : 'Lipsesc cheile ') + shown + '. Fișierul pare modificat sau generat de o altă versiune a programului; rulează din nou programul.';
  }

  /**
   * Verifică forma datelor. Întoarce { ok, errors } cu mesaje în română; nu aruncă
   * niciodată (nici pe obiecte ostile) și ignoră cheile necunoscute (versiuni viitoare).
   */
  function validate(data) {
    try {
      if (data === null || data === undefined) {
        return { ok: false, errors: ['Nu am primit niciun conținut pentru raport. ' + FILE_HINT] };
      }
      if (!isPlain(data)) {
        return { ok: false, errors: ['Fișierul nu conține un obiect JSON, ci ' + describeValue(data) + '. ' + FILE_HINT] };
      }
      const ctx = { problems: [], missing: [] };
      walk(data, SCHEMA, '', ctx);
      if (!ctx.problems.length && !ctx.missing.length && isPlain(data.paid)) walk(data, PAID_ROWS, '', ctx);
      const errors = [];
      const topMissing = ctx.missing.filter((k) => k.indexOf('.') < 0);
      const nestedMissing = ctx.missing.filter((k) => k.indexOf('.') >= 0);
      if (topMissing.length) errors.push(missingMessage(topMissing, true));
      // Grupăm cheile lipsă pe obiectul părinte: un singur mesaj pentru „big”, nu câte unul per cheie.
      const byParent = new Map();
      nestedMissing.forEach((k) => {
        const cut = k.lastIndexOf('.');
        const parent = k.slice(0, cut);
        if (!byParent.has(parent)) byParent.set(parent, []);
        byParent.get(parent).push(k.slice(cut + 1));
      });
      byParent.forEach((keys, parent) => { errors.push(parent + ': ' + missingMessage(keys, false)); });
      ctx.problems.forEach((p) => errors.push(p));
      [['by_year_category', data.by_year_category], ['paid.by_year_category', isPlain(data.paid) ? data.paid.by_year_category : null]].forEach(([name, yc]) => {
        if (errors.length || !isPlain(yc)) return;
        yc.years.forEach((y) => {
          if (!hasOwn(yc.values, y)) errors.push(name + '.values nu are anul „' + clip(y, 12) + '” din ' + name + '.years.');
        });
      });
      if (errors.length > ERRORS_SHOWN) {
        const extra = errors.length - ERRORS_SHOWN;
        errors.length = ERRORS_SHOWN;
        errors.push('… și încă ' + count(extra, 'problemă', 'probleme') + ' asemănătoare.');
      }
      return { ok: errors.length === 0, errors };
    } catch (e) {
      return { ok: false, errors: ['Nu am putut verifica datele (fișierul are o structură neobișnuită). ' + FILE_HINT] };
    }
  }

  /* ---------------------------------------------------------------------------
     Construcție DOM (doar textContent: numele de produse sunt date neîncrezute).
     --------------------------------------------------------------------------- */
  const SVG_NS = 'http://www.w3.org/2000/svg';

  function applyAttrs(el, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach((k) => {
      const v = attrs[k];
      if (v === false || v === null || v === undefined) return;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'style') Object.keys(v).forEach((p) => { el.style.setProperty(p, v[p]); }); // CSSOM, nu atribut: merge și cu CSP strict
      else el.setAttribute(k, v === true ? '' : String(v));
    });
  }
  function appendKids(el, kids) {
    kids.forEach((kid) => {
      if (Array.isArray(kid)) { appendKids(el, kid); return; }
      if (kid === null || kid === undefined || kid === false) return;
      el.appendChild(typeof kid === 'object' && kid.nodeType ? kid : document.createTextNode(String(kid)));
    });
  }
  function h(tag, attrs) {
    const el = document.createElement(tag);
    applyAttrs(el, attrs);
    appendKids(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }
  function sv(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    applyAttrs(el, attrs);
    appendKids(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }
  /** Text static cu „eMAG” înfășurat în translate="no" (numele de brand nu se traduce automat). */
  function rich(text) {
    return String(text).split(/(eMAG)/).map((part) => (part === 'eMAG' ? h('span', { translate: 'no' }, part) : part));
  }

  /* ---------------------------------------------------------------------------
     Linkuri spre eMAG. Valorile de mai jos le repetă pe cele din emag_spend/order_links.py (ORDER_URL_PREFIX,
     ORDER_ID_PATTERN): tests/test_order_links.py verifică paritatea. Un număr se validează STRICT înainte să devină
     adresă: analiza.json poate veni din orice sursă, iar un număr ciudat („../”, „?”, litere) nu are voie să producă
     niciodată un link; el rămâne text. Linkul se deschide doar la clic, în filă nouă, fără legătură cu fereastra
     noastră și fără să trimită adresa de unde vine (noopener, noreferrer, no-referrer).
     --------------------------------------------------------------------------- */
  const ORDER_URL_PREFIX = 'https://www.emag.ro/history/shoppingdetails/';
  // Cifre ASCII, 3–15: acoperă orice număr real și nu lasă loc de text, „..” sau „/” în adresă.
  const ORDER_ID_PATTERN = '[0-9]{3,15}';
  const ORDER_ID_RE = new RegExp('^' + ORDER_ID_PATTERN + '$');
  const RETURN_URL_PREFIX = 'https://www.emag.ro/user/return-history/';
  // Adresa reală a unui retur: <prefix><număr>/<numărul returului>. Python o dă gata construită (din calea salvată la
  // citire); JavaScript o acceptă doar dacă are exact forma asta și numărul returului din ea e cel din rând.
  const RETURN_URL_TAIL_RE = new RegExp('^[0-9]{1,15}/(' + ORDER_ID_PATTERN + ')$');
  const LINK_ATTRS = { target: '_blank', rel: 'noopener noreferrer', referrerpolicy: 'no-referrer' };

  /** Adresa comenzii pe eMAG, sau null dacă `id` nu e un text de 3–15 cifre. */
  function orderUrl(id) {
    return typeof id === 'string' && ORDER_ID_RE.test(id) ? ORDER_URL_PREFIX + id : null;
  }
  /** `url` doar dacă e adresa unui retur pe eMAG și poartă chiar numărul `returnId`; altfel null (rândul rămâne fără link). */
  function returnUrl(returnId, url) {
    if (typeof returnId !== 'string' || !ORDER_ID_RE.test(returnId) || typeof url !== 'string') return null;
    if (url.indexOf(RETURN_URL_PREFIX) !== 0) return null;
    const tail = RETURN_URL_TAIL_RE.exec(url.slice(RETURN_URL_PREFIX.length));
    return tail && tail[1] === returnId ? url : null;
  }
  /** Link vizibil permanent (text + săgeată), cu etichetă pentru cititoarele de ecran; săgeata e decorativă. */
  function emagLink(url, label, text) {
    return h('a', Object.assign({ class: 'ed-olink', href: url, 'aria-label': label }, LINK_ATTRS),
      h('span', null, text), h('span', { class: 'ed-ext', 'aria-hidden': 'true' }, '↗'));
  }
  /**
   * Numărul comenzii ca link; dacă nu e valid, doar textul (tăiat), fără link. `plain === true` (date de demonstrație):
   * tot text, fiindcă numerele sunt inventate, eMAG nu le cunoaște și ar trimite utilizatorul la lista de comenzi.
   */
  function orderLink(id, plain) {
    const url = plain === true ? null : orderUrl(id);
    if (url === null) return typeof id === 'string' ? clip(id, INVALID_ID_SHOWN) : '';
    return emagLink(url, 'Deschide comanda ' + id + ' pe eMAG (filă nouă)', id);
  }
  /** Link spre retur (text „retur 123”) dacă adresa e validă, altfel doar textul „retur 123”; `plain === true`: mereu text. */
  function returnLink(returnId, url, plain) {
    const text = 'retur ' + (typeof returnId === 'string' ? clip(returnId, INVALID_ID_SHOWN) : '');
    const valid = plain === true ? null : returnUrl(returnId, url);
    return valid === null ? text : emagLink(valid, 'Deschide returul ' + returnId + ' pe eMAG (filă nouă)', text);
  }
  /**
   * Numele unui produs ca link spre comanda lui pe eMAG, cu aceleași reguli ca numărul comenzii: doar dintr-un număr valid,
   * în filă nouă, fără legătură cu fereastra noastră, și niciodată în date de demonstrație (`plain === true`). Textul vizibil
   * rămâne numele (stilul de link apare la hover și la focus, vezi .ed-plink); eticheta pentru cititoarele de ecran începe cu
   * numele și spune ce comandă se deschide: la un rând care adună `orderCount` > 1 comenzi, pe cea mai recentă.
   * Fără număr valid, numele rămâne text, trecut prin rich() ca orice text din date.
   */
  function productLink(name, orderId, orderCount, plain) {
    const text = typeof name === 'string' ? name : '';
    const url = plain === true ? null : orderUrl(orderId);
    if (url === null) return rich(text);
    const latest = typeof orderCount === 'number' && orderCount > 1 ? ' (cea mai recentă din ' + int(orderCount) + ')' : '';
    return h('a', Object.assign({ class: 'ed-plink', href: url, 'aria-label': text + ': Deschide comanda ' + orderId + ' pe eMAG' + latest + ', în filă nouă' },
      LINK_ATTRS), rich(text));
  }
  /**
   * Celula „Data și comanda”: data pe primul rând, linkul comenzii pe al doilea. Împreună într-o singură coloană, ca tabelele
   * late („Achiziții peste prag” are 8 coloane) să nu primească încă una și să nu iasă din chenar la 1280 px.
   */
  function dateAndOrder(date, orderId, plain) {
    return [fmtDate(date), h('span', { class: 'ed-orderline' }, orderLink(orderId, plain))];
  }

  const STATE_LABEL = { kept: 'Păstrat', returned: 'Returnat', cancelled: 'Anulat', pending: 'În curs', unknown: 'Necunoscut' };
  const STATE_COLOR = {
    kept: 'var(--ed-kept)', returned: 'var(--ed-returned)', cancelled: 'var(--ed-cancelled)',
    pending: 'var(--ed-pending)', unknown: 'var(--ed-unknown)',
  };
  const stateLabel = (s) => (hasOwn(STATE_LABEL, s) ? STATE_LABEL[s] : String(s));
  const stateColor = (s) => (hasOwn(STATE_COLOR, s) ? STATE_COLOR[s] : 'var(--ed-muted)');
  // „Altele” = OTHER_LABEL din spend_analysis.py; dacă se redenumește acolo, seria doar primește culoarea ei obișnuită.
  const seriesColor = (name, i) => (name === 'Altele' ? 'var(--ed-other)' : 'var(--ed-s' + ((i % SERIES_COLORS) + 1) + ')');

  /**
   * Copie explicită a cheilor pe care le citește raportul, cu cele opționale completate gol.
   * Nu folosește Object.assign pe date: o cheie „__proto__” din fișier nu are voie să schimbe prototipul.
   */
  function withDefaults(d) {
    return {
      meta: d.meta, funnel: d.funnel, orders: d.orders, by_category: d.by_category, by_year: d.by_year,
      by_year_category: d.by_year_category, top_products: d.top_products, by_seller: d.by_seller, big: d.big,
      reconciliation: d.reconciliation, returns: d.returns, warnings: d.warnings,
      highlights: d.highlights || {},
      paid_only: d.paid_only || [],
      in_progress: d.in_progress || [],
      uncategorized: d.uncategorized || [],
      uncategorized_count: typeof d.uncategorized_count === 'number' ? d.uncategorized_count : (d.uncategorized || []).length,
      price_history: d.price_history || null, // lipsa cheii = raport vechi: blocul de prețuri nu se desenează
      warnings_detail: d.warnings_detail || null, // lipsa cheii = lista simplă de texte
      paid: isPlain(d.paid) ? d.paid : null, // lipsa cheii = raport vechi: sumele se arată la preț de listă, ca înainte
    };
  }

  /** Semnul și suma, pentru descompunerea cifrei mari: „+1.231,15 Lei”, „−5,56 Lei”. */
  const signedLei = (bani) => (num(bani) < 0 ? MINUS : '+') + lei(Math.abs(num(bani)));

  // Ce înseamnă fiecare rând care nu e produs (cheia `key` din paid.extra_rows): explicația din tooltip și din nota de sub bare.
  const EXTRA_ROW_NOTES = {
    fees: 'transportul, serviciile și taxele comenzilor livrate; nu se împart pe produse',
    credit_returns: 'produse returnate cu voucher sau sold eMAG: banii nu s-au întors în cont, iar voucherul scade „Total plătit” al comenzii în care îl folosești',
    refund_differences: 'partea plătită a produselor returnate minus suma restituită afișată la retur',
  };

  /**
   * Micro-diagramă SVG a prețului pe bucată la fiecare cumpărare (de la cea mai veche la cea mai nouă). Orizontal,
   * punctele urmăresc datele când toate sunt valide și diferite (altfel stau la distanțe egale); vertical, de la minim
   * la maxim. Minimul e cerc gol, ultimul preț e punct plin: se deosebesc și fără culoare. Eticheta spune cifrele.
   */
  function sparkline(product) {
    const buys = product.purchases;
    const values = buys.map((b) => num(b.unit_bani));
    const lo = Math.min(...values), hi = Math.max(...values);
    const times = buys.map((b) => {
      const m = typeof b.date === 'string' ? ISO_DATE.exec(b.date) : null;
      return m ? utcTime(+m[1], +m[2], +m[3], 0, 0) : null;
    });
    const byDate = times.length > 1 && times.every((t) => t !== null) && Math.max(...times) > Math.min(...times);
    const t0 = byDate ? Math.min(...times) : 0;
    const span = byDate ? Math.max(...times) - t0 : 0;
    const inner = SPARK_WIDTH - 2 * SPARK_PAD;
    const x = (i) => SPARK_PAD + (buys.length < 2 ? inner / 2 : (byDate ? (times[i] - t0) / span : i / (buys.length - 1)) * inner);
    const y = (v) => (hi === lo ? SPARK_HEIGHT / 2 : SPARK_PAD + (1 - (v - lo) / (hi - lo)) * (SPARK_HEIGHT - 2 * SPARK_PAD));
    const minIndex = values.indexOf(lo), lastIndex = values.length - 1;
    const withDate = (i) => lei(values[i]) + (buys[i].date ? ' (' + fmtDate(buys[i].date) + ')' : '');
    const label = 'Prețul pe bucată: de la ' + withDate(0) + ' la ' + withDate(lastIndex) + '; minim ' + lei(lo) + ', maxim ' + lei(hi) + '.';
    const svg = sv('svg', {
      class: 'ed-spark', viewBox: '0 0 ' + SPARK_WIDTH + ' ' + SPARK_HEIGHT, width: SPARK_WIDTH, height: SPARK_HEIGHT,
      role: 'img', focusable: 'false', 'aria-label': label,
    });
    const point = (i, cls, r) => sv('circle', { class: cls, cx: x(i).toFixed(1), cy: y(values[i]).toFixed(1), r });
    if (buys.length > 1) svg.appendChild(sv('polyline', { class: 'ed-spark-line', points: values.map((v, i) => x(i).toFixed(1) + ',' + y(v).toFixed(1)).join(' ') }));
    values.forEach((v, i) => { if (i !== minIndex && i !== lastIndex) svg.appendChild(point(i, 'ed-spark-dot', 1.6)); });
    if (minIndex !== lastIndex) svg.appendChild(point(minIndex, 'ed-spark-min', 3));
    svg.appendChild(point(lastIndex, 'ed-spark-last', 3));
    return svg;
  }

  /** Numele categoriilor evidențiate, într-un titlu citibil: „Alcool și televizoare”. */
  function highlightsTitle(names) {
    if (!names.length) return 'Categorii evidențiate';
    const lower = names.map((n, i) => (i === 0 ? n : n.charAt(0).toLowerCase() + n.slice(1)));
    return lower.length === 1 ? lower[0] : lower.slice(0, -1).join(', ') + ' și ' + lower[lower.length - 1];
  }

  /* ---------------------------------------------------------------------------
     Instanța: tot ce ține de un singur mount (listener-e, tooltip, observator).
     --------------------------------------------------------------------------- */
  const INSTANCES = new WeakMap();

  function createInstance(root, options) {
    const opts = options && typeof options === 'object' ? options : {};
    // Date de demonstrație (opțiunea `demo` a gazdei sau `meta.demo` din analiza.json): comenzile sunt inventate, deci
    // numerele lor rămân text. Se stabilește la fiecare desenare, din datele primite.
    let demoMode = false;
    const level =Math.min(5, Math.max(1, Math.round(Number(opts.headingLevel)) || HEADING_LEVEL_DEFAULT));
    const hTag = (offset) => 'h' + Math.min(6, level + offset);
    const listeners = [];
    const scrollers = [];
    const self = { ok: false, errors: [], unmount: null };
    let mounted = true;
    let addedClass = false;
    let observer = null;
    let frame = 0;
    let announceTimer = 0; // anunțul „N produse găsite” după o pauză în căutare; unmount îl oprește
    let wrap = null, tip = null, tipTarget = null, tipArgs = null, live = null;
    let redrawChart = null;
    let seenConnected = false; // rădăcina a fost cândva în document (altfel „scoasă din document” n-ar avea sens)

    /** Listener pe elemente care trăiesc cât instanța (root, window); unmount le scoate. */
    function listen(target, type, fn, options2) {
      target.addEventListener(type, fn, options2);
      listeners.push([target, type, fn, options2]);
    }
    function announce(message) { if (live) live.textContent = message; }

    /* ----- tooltip (mouse, focus de la tastatură, Escape îl închide) ----- */
    function hideTip() { if (tip) tip.hidden = true; tipTarget = null; tipArgs = null; }
    function showTip(el, ev, title, rows) {
      if (tipTarget !== el) {
        tip.replaceChildren(h('div', { class: 'ed-tip-title' }, rich(title)), ...rows.map((r) => h('div', { class: 'ed-tip-row' },
          h('span', { class: 'ed-tip-k' }, r.color ? h('i', { style: { background: r.color } }) : null, rich(r.label)),
          h('span', { class: 'ed-tip-v' }, r.value))));
        tipTarget = el;
        tipArgs = [el, title, rows];
      }
      tip.hidden = false;
      tip.style.left = '0px'; tip.style.top = '0px';
      const box = tip.getBoundingClientRect();
      const anchor = el.getBoundingClientRect();
      const fromPointer = ev && ev.type && ev.type.indexOf('pointer') === 0 && ev.clientX > 0;
      let x = fromPointer ? ev.clientX + 14 : anchor.left + 12;
      let y = fromPointer ? ev.clientY + 14 : anchor.bottom + 6;
      if (y + box.height > innerHeight - 8) y = fromPointer ? ev.clientY - box.height - 14 : anchor.top - box.height - 6;
      x = Math.max(8, Math.min(x, innerWidth - box.width - 8));
      y = Math.max(8, y);
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
      // Un strămoș cu transform/filter face din el blocul de referință pentru position:fixed; corectăm diferența.
      const got = tip.getBoundingClientRect();
      if (Math.abs(got.left - x) > 1 || Math.abs(got.top - y) > 1) {
        tip.style.left = (x - (got.left - x)) + 'px'; tip.style.top = (y - (got.top - y)) + 'px';
      }
    }
    /**
     * La derulare, tooltip-ul de la mouse se închide (elementul de sub cursor s-a schimbat), dar cel al
     * elementului cu focus rămâne lângă el: Tab spre ceva din afara ecranului derulează pagina singur.
     */
    function onScroll() {
      if (releasedByHost() || !tipTarget) return;
      if (tipTarget === tipTarget.ownerDocument.activeElement && tipArgs) showTip(tipArgs[0], null, tipArgs[1], tipArgs[2]);
      else hideTip();
    }
    /** Tooltip la mouse și la focus; pe touch, atingerea mută focusul și arată același tooltip. */
    function attachTip(el, title, rows) {
      const fromMouse = (e) => { if (e.pointerType !== 'touch') showTip(el, e, title, rows); };
      el.addEventListener('pointerenter', fromMouse);
      el.addEventListener('pointermove', fromMouse);
      el.addEventListener('pointerleave', hideTip);
      el.addEventListener('focus', (e) => showTip(el, e, title, rows));
      el.addEventListener('blur', hideTip);
    }

    /* ----- zone derulabile: focusabile doar când chiar se derulează (tastatura trebuie să ajungă la ele) ----- */
    function trackScroll(el, label) {
      el.setAttribute('role', 'group');
      el.setAttribute('aria-label', label);
      scrollers.push(el);
      return el;
    }
    /**
     * Scoate din evidență zonele derulabile aflate în `container`, chiar înainte ca acesta să fie rescris
     * (filtru, „Arată încă”). Fără asta, `scrollers` ar ține în viață fiecare tabel vechi, detașat din DOM.
     * Nu se bazează pe isConnected: la prima desenare nimic nu e încă în document.
     */
    function forgetScrollers(container) {
      for (let i = scrollers.length - 1; i >= 0; i--) if (container.contains(scrollers[i])) scrollers.splice(i, 1);
    }
    function refreshScrollers() {
      scrollers.forEach((el) => {
        if (!el.isConnected) return;
        const overflows = el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
        if (overflows) el.setAttribute('tabindex', '0'); else el.removeAttribute('tabindex');
      });
    }
    /**
     * Plasă de siguranță: dacă gazda a scos rădăcina din document fără unmount(), instanța nu rămâne
     * agățată de window (ascultătorul de scroll) și de ResizeObserver; se dezmontează singură.
     * Înainte de prima atașare în document nu face nimic (gazda poate monta într-o rădăcină încă detașată).
     */
    function releasedByHost() {
      if (root.isConnected) { seenConnected = true; return false; }
      if (!seenConnected) return false;
      unmount();
      return true;
    }
    function scheduleLayout() {
      if (frame || !mounted) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!mounted || releasedByHost()) return;
        if (redrawChart) redrawChart();
        refreshScrollers();
      });
    }

    /* ----- piese comune ----- */
    /** Un bloc major al raportului; `data-ed-block` / `data-ed-title` sunt contractul cu site-ul (adnotări). */
    function block(name, title) {
      return h('section', { class: 'ed-block', 'data-ed-block': name, 'data-ed-title': title }, Array.prototype.slice.call(arguments, 2));
    }
    function heading(title, offset, extraClass) {
      return h(hTag(offset || 0), { class: 'ed-h' + (extraClass ? ' ' + extraClass : '') }, title);
    }
    /**
     * Celulă de tabel. Textul din date trece prin rich() (numele „eMAG” nu se traduce automat);
     * `data-label` e eticheta coloanei, afișată de CSS când tabelul devine listă de carduri.
     */
    function cell(col, content, asCards) {
      const cls = [col.num ? 'ed-num' : '', col.name ? 'ed-name' : '', col.nowrap ? 'ed-nowrap' : ''].filter(Boolean).join(' ');
      // Text gol = fără nod de text: așa `td:empty` din CSS ascunde în carduri câmpurile fără conținut.
      return h('td', { class: cls || null, 'data-label': asCards ? col.label : null, role: asCards ? 'cell' : null },
        typeof content === 'string' ? (content === '' ? null : rich(content)) : content);
    }
    /**
     * Tabel cu antet pentru cititoarele de ecran. Cu `asCards`, pe lățime mică CSS-ul îl face listă de carduri
     * (câte un card pe rând, cu etichetele coloanelor); rolurile ARIA explicite păstrează semantica de tabel
     * și când display-ul elementelor se schimbă (Safari o pierde altfel). `extraClass` (opțional) se adaugă la clasa
     * tabelului pentru stiluri proprii (tabelul de prețuri).
     */
    function buildTable(title, head, rows, foot, asCards, extraClass) {
      const role = (name) => (asCards ? { role: name } : null);
      return h('table', Object.assign({ class: [asCards ? 'ed-tbl-cards' : '', extraClass || ''].filter(Boolean).join(' ') || null }, role('table')),
        h('caption', { class: 'ed-sr' }, title),
        h('thead', role('rowgroup'), h('tr', role('row'), head.map((c) => h('th', Object.assign({ scope: 'col', class: c.num ? 'ed-num' : null }, role('columnheader')), c.label)))),
        h('tbody', role('rowgroup'), rows.map((r) => h('tr', role('row'), r.map((c, i) => cell(head[i] || {}, c, asCards))))),
        foot ? h('tfoot', role('rowgroup'), h('tr', role('row'), foot.map((c, i) => cell(head[i] || {}, c, asCards)))) : null);
    }
    function tableWrap(title, table) {
      return trackScroll(h('div', { class: 'ed-tbl-wrap' }, table), 'Tabel: ' + title);
    }
    function pill(state, extra) {
      return h('span', { class: 'ed-pill' }, h('i', { class: 'ed-sw', 'aria-hidden': 'true', style: { background: stateColor(state) } }), h('span', null, stateLabel(state), extra || null));
    }
    function emptyNote(text) { return h('p', { class: 'ed-note' }, text); }
    /** Buton „Vezi tabel”: aceeași etichetă mereu, starea stă în aria-pressed (modelul standard de comutator). */
    function wireToggle(button, chartEls, tableEl, buildTableInto, onChart) {
      let built = false;
      button.addEventListener('click', () => {
        const showTable = button.getAttribute('aria-pressed') !== 'true';
        button.setAttribute('aria-pressed', String(showTable));
        if (showTable && !built) { tableEl.replaceChildren(buildTableInto()); built = true; }
        tableEl.hidden = !showTable;
        chartEls.forEach((e) => { e.hidden = showTable; });
        hideTip();
        announce(showTable ? 'Tabelul e afișat în locul graficului.' : 'Graficul e afișat.');
        if (showTable) refreshScrollers(); else if (onChart) onChart();
      });
    }
    function toggleButton() {
      return h('button', { class: 'ed-toggle', type: 'button', 'aria-pressed': 'false' }, 'Vezi tabel');
    }

    /** Buton „Arată încă N (M rămase)”, același la toate listele și tabelele lungi. */
    function moreButton(remaining, step) {
      return h('button', { class: 'ed-more', type: 'button' }, 'Arată încă ' + int(Math.min(step || ROWS_PAGE, remaining)) + ' (' + int(remaining) + ' rămase)');
    }
    /**
     * Desenare treptată: primele ROWS_PAGE rânduri, apoi „Arată încă”. `build(felie)` desenează lista sau
     * tabelul pentru rândurile primite. Sub o pagină întoarce direct rezultatul lui `build`, fără înveliș.
     */
    function paged(items, build) {
      if (items.length <= ROWS_PAGE) return build(items);
      const host = h('div', { class: 'ed-stack', tabindex: '-1' });
      let limit = ROWS_PAGE;
      function draw(byUser) {
        const remaining = items.length - limit;
        const more = remaining > 0 ? moreButton(remaining) : null;
        if (more) more.addEventListener('click', () => { limit += ROWS_PAGE; draw(true); });
        forgetScrollers(host);
        host.replaceChildren(...[build(items.slice(0, limit)), more].filter(Boolean));
        if (!byUser) return; // la prima desenare nu se anunță nimic și nu se mută focusul
        (more || host).focus({ preventScroll: true });
        refreshScrollers();
        announce('Se afișează ' + count(Math.min(limit, items.length), 'rând', 'rânduri') + ' din ' + int(items.length) + '.');
      }
      draw(false);
      return host;
    }
    /**
     * Un singur punct de oprire Tab pentru un șir de rânduri focusabile care doar arată un tooltip: Tab intră
     * pe rândul curent, săgețile Sus/Jos, Home și End mută focusul. Altfel 30 de rânduri ar fi 30 de opriri.
     */
    function rovingFocus(container, rows) {
      if (!rows.length) return;
      let current = 0;
      rows.forEach((row, index) => {
        row.setAttribute('tabindex', index === 0 ? '0' : '-1');
        row.addEventListener('focus', () => {
          rows[current].setAttribute('tabindex', '-1');
          current = index;
          row.setAttribute('tabindex', '0');
        });
      });
      container.addEventListener('keydown', (e) => {
        const target = { ArrowDown: current + 1, ArrowUp: current - 1, Home: 0, End: rows.length - 1 }[e.key];
        if (target === undefined || e.altKey || e.ctrlKey || e.metaKey) return;
        e.preventDefault(); // și derularea paginii cu săgețile
        rows[Math.max(0, Math.min(rows.length - 1, target))].focus();
      });
    }

    /**
     * Listă de bare orizontale (categorii, vânzători): fiecare rând are tooltip, iar lista întreagă e UN
     * singur punct de oprire Tab (rovingFocus). Lățimea barelor se raportează la maximul tuturor
     * rândurilor, nu al paginii curente, ca „Arată încă” să nu schimbe scara. Un rând fără `units` (de ex.
     * „Transport și taxe”) nu arată bucăți, iar cu `extra: true` bara lui are culoarea rândurilor care nu sunt produse.
     */
    function barList(items, total) {
      const max = items.reduce((m, i) => Math.max(m, i.bani), 1);
      return paged(items, (slice) => {
        const ul = h('ul', { class: 'ed-bars', role: 'list' }); // role explicit: Safari scoate lista când list-style e none
        const rows = slice.map((i) => {
          const width = Math.max(0, Math.min(100, i.bani / max * 100));
          const units = typeof i.units === 'number' ? buc(i.units) : null;
          const row = h('li', {
            class: 'ed-bar-row' + (i.extra ? ' ed-bar-extra' : ''),
            'aria-label': i.name + ': ' + lei(i.bani) + ', ' + pct(i.bani, total) + (units ? ', ' + units : ''),
          },
          h('span', { class: 'ed-bar-name' }, rich(i.name)),
          h('span', { class: 'ed-bar-val' }, h('strong', null, lei(i.bani)), ' ', h('span', { class: 'ed-pct' }, '· ' + pct(i.bani, total) + (units ? ' · ' + units : ''))),
          h('span', { class: 'ed-bar-track', 'aria-hidden': 'true' }, h('span', { class: 'ed-bar-fill', style: { width: width.toFixed(2) + '%' } })));
          attachTip(row, i.name, i.tip);
          ul.appendChild(row);
          return row;
        });
        rovingFocus(ul, rows);
        return ul;
      });
    }

    /* =========================== blocurile raportului =========================== */

    /** Descompunerea cifrei mari: preț de listă, reduceri, transport și taxe și, dacă există, retururile cu credit și diferențele. */
    function heroParts(P) {
      const parts = [['La preț de listă', lei(P.list_kept_bani)], ['reduceri', MINUS + lei(Math.abs(num(P.discounts_kept_bani)))],
        ['transport și taxe', signedLei(P.fees_bani)]];
      if (P.credit_returns_bani) parts.push(['retururi cu voucher sau sold', signedLei(P.credit_returns_bani)]);
      if (P.refund_differences_bani) parts.push(['diferențe la restituiri', signedLei(P.refund_differences_bani)]);
      return h('ul', { class: 'ed-hero-parts', role: 'list', 'aria-label': 'Cum se compune suma' },
        parts.map((p) => h('li', null, rich(p[0]), ' ', h('span', { class: 'ed-hero-part-v' }, p[1]))));
    }

    function heroBlock(D) {
      const M = D.meta, O = D.orders, P = D.paid;
      const F = P ? P.funnel : D.funnel;
      const spent = P ? F.spent_bani : F.kept_bani, units = P ? F.spent_units : F.kept_units;
      const parts = splitMoney(spent);
      let period = 'Nicio comandă în aceste date.';
      if (M.first_order && M.last_order) period = 'Comenzi din ' + fmtDate(M.first_order) + ' până în ' + fmtDate(M.last_order);
      period += ' · generat ' + fmtDate(M.generated_at, true);
      const away = F.cancelled_bani + F.returned_bani + F.pending_bani + F.unknown_bani;
      let summary = 'Nu există produse comandate în aceste date.';
      if (F.ordered_bani > 0 && P) {
        summary = buc(units) + ' păstrate din ' + count(O.total, 'comandă', 'comenzi') + '. ' + (away
          ? 'Din ' + lei(F.ordered_bani) + ' comandați (după reduceri), ' + lei(away) + ' au fost anulați, returnați cu bani înapoi sau nu au ajuns încă.'
          : 'Nimic din ce ai comandat nu a fost anulat, returnat cu bani înapoi sau în curs.');
      } else if (F.ordered_bani > 0) {
        summary = buc(units) + ' păstrate din ' + count(O.total, 'comandă', 'comenzi') + '. ' + (F.kept_bani === F.ordered_bani
          ? 'Tot ce ai comandat (' + lei(F.ordered_bani) + ') ai păstrat.'
          : 'Din ' + lei(F.ordered_bani) + ' comandați, restul a fost anulat, returnat sau nu a ajuns încă.');
      }
      return block('hero', 'Cât ai cheltuit', h('div', { class: 'ed-card ed-hero' },
        heading('Cât ai cheltuit', 0, 'ed-eyebrow'),
        h('p', { class: 'ed-amount' }, h('span', { class: 'ed-big' }, parts.whole), h('span', { class: 'ed-cents' }, parts.frac + NBSP + 'Lei')),
        h('p', { class: 'ed-lead' }, P
          ? 'Banii plătiți efectiv pe ce ai păstrat: după reduceri și vouchere, cu transportul și taxele, minus banii primiți înapoi la retururi.'
          : 'Pe produsele livrate și ridicate, fără cele returnate, la preț de listă (raport făcut de o versiune mai veche a programului).'),
        P ? heroParts(P) : null,
        h('p', { class: 'ed-caption' }, summary),
        h('p', { class: 'ed-meta-line' }, period),
        F.unknown_bani > 0
          ? h('p', { class: 'ed-hero-warn' }, 'Atenție: ' + lei(F.unknown_bani) + ' din comenzi au un status pe care programul nu îl recunoaște. Nu sunt numărate ca livrate.')
          : null));
    }

    /**
     * Lanțul de la comandat la ce ai păstrat. Cu `paid`: în bani plătiți (după reduceri) — comandat − anulat − returnat cu bani
     * înapoi − în curs + transport și taxe = plătit efectiv; bara împarte totalul (comandat + transport) pe stări. Fără `paid`
     * (raport vechi): la preț de listă, ca înainte.
     */
    function funnelBlock(D) {
      const P = D.paid;
      const F = P ? P.funnel : D.funnel;
      const base = P ? F.ordered_bani + F.fees_bani : F.ordered_bani; // baza procentelor: suma barei
      const share = P ? ' din total' : ' din comandat';
      const kept = P
        ? { key: 'kept', name: 'Plătit efectiv (păstrat)', bani: F.spent_bani, units: F.spent_units }
        : { key: 'kept', name: 'Păstrat (livrat / ridicat)', bani: F.kept_bani, units: F.kept_units };
      const minus = [
        { key: 'cancelled', name: 'Anulat', bani: F.cancelled_bani, units: F.cancelled_units },
        { key: 'returned', name: P ? 'Returnat, bani primiți înapoi' : 'Returnat', bani: F.returned_bani, units: F.returned_units },
        { key: 'pending', name: 'În curs (nelivrat încă)', bani: F.pending_bani, units: F.pending_units },
      ];
      if (F.unknown_bani) minus.push({ key: 'unknown', name: 'Status necunoscut', bani: F.unknown_bani, units: F.unknown_units });
      const barOrder = [kept, minus[1], minus[0], minus[2]].concat(minus.slice(3));
      const bar = h('div', { class: 'ed-funnel-bar', role: 'group', 'aria-label': P
        ? 'Împărțirea sumei comandate: plătit efectiv, returnat, anulat, în curs'
        : 'Împărțirea valorii comandate: păstrat, returnat, anulat, în curs' });
      barOrder.forEach((f) => {
        if (!(f.bani > 0)) return;
        const seg = h('div', {
          class: 'ed-funnel-seg', tabindex: '0', role: 'img', 'aria-label': f.name + ': ' + lei(f.bani) + ', ' + pct(f.bani, base) + share,
          style: { flex: f.bani + ' 1 0', background: stateColor(f.key) },
        });
        attachTip(seg, f.name, [{ label: 'Valoare', value: lei(f.bani) }, { label: 'Bucăți', value: buc(f.units) }, { label: P ? 'Din total' : 'Din comandat', value: pct(f.bani, base) }]);
        bar.appendChild(seg);
      });
      const item = (f, prefix, ring, extraClass) => h('div', { class: 'ed-fl-item' + (extraClass ? ' ' + extraClass : '') },
        h('span', { class: 'ed-fl-name' }, h('i', { class: 'ed-sw' + (ring ? ' ed-sw-ring' : ''), 'aria-hidden': 'true', style: { background: f.key ? stateColor(f.key) : 'transparent' } }), f.name),
        h('span', { class: 'ed-fl-val' }, prefix + lei(f.bani)),
        h('span', { class: 'ed-fl-meta' }, f.meta || (buc(f.units) + ' · ' + pct(f.bani, base) + share)));
      const ordered = P
        ? { key: null, name: 'Comandat (după reduceri)', bani: F.ordered_bani, meta: buc(F.ordered_units) + ' · toate comenzile, fără asigurări' }
        : { key: null, name: 'Comandat în total', bani: F.ordered_bani, meta: buc(F.ordered_units) + ' · toate comenzile, fără asigurări' };
      const legend = h('div', { class: 'ed-funnel-legend' },
        item(ordered, '', true),
        minus.map((f) => item(f, MINUS + NBSP, false)),
        P ? item({ key: null, name: 'Transport și taxe', bani: F.fees_bani, meta: 'comenzile livrate; nu se împart pe produse' }, '+' + NBSP, true) : null,
        item(kept, '=' + NBSP, false, 'ed-fl-final'));
      const notes = [];
      if (P && P.credit_returns_bani) {
        notes.push(h('p', { class: 'ed-note' }, rich('Plătit efectiv include ' + lei(P.credit_returns_bani) + ' pe ' + buc(P.credit_returns_units) +
          ' returnate cu voucher sau sold eMAG: banii nu s-au întors în cont, iar voucherul scade „Total plătit” al comenzii în care îl folosești (altfel s-ar scădea de două ori).')));
      }
      if (P && P.refund_differences_bani) {
        notes.push(h('p', { class: 'ed-note' }, 'Și ' + signedLei(P.refund_differences_bani) + ' diferențe la restituiri: partea plătită a produselor returnate minus suma restituită afișată la retur.'));
      }
      const empty = !barOrder.some((f) => f.bani > 0);
      const title = P ? 'De la comandat la plătit' : 'De la comandat la păstrat';
      return block('funnel', title,
        heading(title),
        h('p', { class: 'ed-caption' }, P
          ? 'Sumele sunt cele plătite: după reduceri și vouchere. Din ce ai comandat se scad anulările, banii primiți înapoi la retururi și ce nu a ajuns încă; transportul și taxele comenzilor livrate se adaugă.'
          : 'Din valoarea comandată se scad anulatele, returnatele și ce nu a ajuns încă. Ce rămâne e ce ai păstrat.'),
        h('div', { class: 'ed-card ed-stack' }, empty ? emptyNote('Nu există comenzi de afișat.') : bar, legend, notes));
    }

    function tilesBlock(D) {
      const P = D.paid, O = D.orders, big = D.big;
      const F = P ? P.funnel : D.funnel;
      let ordersDesc = 'comenzi în cont: ' + int(O.kept_all) + ' păstrate integral, ' + int(O.kept_partial) + ' parțial, ' +
        int(O.returned_all) + ' returnate, ' + int(O.cancelled_all) + ' anulate';
      if (O.in_progress) ordersDesc += ', ' + int(O.in_progress) + ' în curs';
      if (O.unknown) ordersDesc += ', ' + int(O.unknown) + ' cu status necunoscut';
      const tiles = [
        { num: int(O.total), desc: ordersDesc },
        { num: lei(F.returned_bani), desc: (P ? 'primit înapoi la retururi (' : 'returnat (') + buc(F.returned_units) + '), scăzut din total' },
        { num: lei(F.cancelled_bani), desc: 'anulat (' + buc(F.cancelled_units) + '), scăzut din total' },
        { num: int(big.kept_units), desc: P
          ? 'produse păstrate peste ' + lei(big.threshold_bani) + ' bucata (preț de listă), plătite ' + lei(big.kept_paid_bani)
          : 'produse păstrate peste ' + lei(big.threshold_bani) + ' bucata, în valoare de ' + lei(big.kept_bani) },
      ];
      Object.keys(D.highlights).forEach((name) => {
        const t = D.highlights[name].totals;
        tiles.push({ num: lei(P ? t.paid_kept_bani : t.kept_bani), desc: name + ': ' + buc(t.kept_units) + ' păstrate' });
      });
      return block('tiles', 'Cifre pe scurt',
        heading('Cifre pe scurt', 0, 'ed-sr'),
        h('ul', { class: 'ed-tiles', role: 'list' }, tiles.map((t) => h('li', { class: 'ed-tile' }, h('p', { class: 'ed-tile-num' }, t.num), h('p', { class: 'ed-tile-desc' }, t.desc)))));
    }

    /** Rândurile categoriilor ca bare: cu `paid`, sumele plătite plus rândurile care nu sunt produse (transport și taxe…). */
    function categoryBars(D) {
      const P = D.paid;
      const bars = D.by_category.filter((c) => (P ? c.paid_kept_bani : c.kept_bani) > 0).map((c) => ({
        name: c.name, bani: P ? c.paid_kept_bani : c.kept_bani, units: c.kept_units,
        tip: (P
          ? [{ label: 'Plătit', value: lei(c.paid_kept_bani) }, { label: 'La preț de listă', value: lei(c.kept_bani) }, { label: 'Bucăți păstrate', value: buc(c.kept_units) },
            { label: 'Comandat', value: lei(c.paid_ordered_bani) }, { label: 'Returnat', value: lei(c.paid_returned_bani) }, { label: 'Anulat', value: lei(c.paid_cancelled_bani) }]
          : [{ label: 'Păstrat', value: lei(c.kept_bani) }, { label: 'Bucăți păstrate', value: buc(c.kept_units) },
            { label: 'Comandat', value: lei(c.ordered_bani) }, { label: 'Returnat', value: lei(c.returned_bani) }, { label: 'Anulat', value: lei(c.cancelled_bani) }])
          .concat((P ? c.paid_pending_bani : c.pending_bani) ? [{ label: 'În curs', value: lei(P ? c.paid_pending_bani : c.pending_bani) }] : []),
      }));
      if (P) {
        P.extra_rows.filter((r) => r.bani !== 0).forEach((r) => bars.push({
          name: r.name, bani: r.bani, units: null, extra: true, tip: [{ label: 'Plătit', value: lei(r.bani) }],
          note: hasOwn(EXTRA_ROW_NOTES, r.key) ? EXTRA_ROW_NOTES[r.key] : '',
        }));
      }
      return bars;
    }

    function categoriesBlock(D) {
      const P = D.paid, F = D.funnel;
      const shown = categoryBars(D);
      const total = P ? P.spent_bani : F.kept_bani;
      const extras = shown.filter((b) => b.extra && b.note);
      const barsHost = h('div', null, shown.length
        ? [barList(shown, total), extras.length ? h('ul', { class: 'ed-extra-notes', role: 'list' },
          extras.map((b) => h('li', null, h('strong', null, rich(b.name)), ': ', rich(b.note), '.'))) : null]
        : emptyNote('Nu există produse păstrate.'));
      const tableHost = h('div', { hidden: 'hidden' });
      const button = toggleButton();
      wireToggle(button, [barsHost], tableHost, () => {
        const head = [{ label: 'Categorie', name: true }, { label: P ? 'Plătit' : 'Păstrat', num: true }, { label: 'Buc', num: true }, { label: 'Comandat', num: true },
          { label: 'Returnat', num: true }, { label: 'Anulat', num: true }, { label: 'În curs', num: true }];
        if (!P) {
          const rows = D.by_category.map((c) => [c.name, lei(c.kept_bani), int(c.kept_units), lei(c.ordered_bani), lei(c.returned_bani), lei(c.cancelled_bani), lei(c.pending_bani)]);
          return tableWrap('Pe categorii', buildTable('Pe categorii', head, rows, ['Total', lei(F.kept_bani), int(F.kept_units), lei(F.ordered_bani), lei(F.returned_bani), lei(F.cancelled_bani), lei(F.pending_bani)]));
        }
        const sum = (k) => D.by_category.reduce((a, c) => a + num(c[k]), 0);
        const rows = D.by_category.map((c) => [c.name, lei(c.paid_kept_bani), int(c.kept_units), lei(c.paid_ordered_bani), lei(c.paid_returned_bani), lei(c.paid_cancelled_bani), lei(c.paid_pending_bani)])
          .concat(P.extra_rows.filter((r) => r.bani !== 0).map((r) => [r.name, lei(r.bani), '', '', '', '', '']));
        return tableWrap('Pe categorii', buildTable('Pe categorii', head, rows, ['Total', lei(P.spent_bani), int(sum('kept_units')), lei(sum('paid_ordered_bani')),
          lei(sum('paid_returned_bani')), lei(sum('paid_cancelled_bani')), lei(sum('paid_pending_bani'))]));
      });
      return block('categories', 'Pe ce s-au dus banii',
        h('div', { class: 'ed-sec-head' }, heading('Pe ce s-au dus banii'), button),
        P
          ? h('p', { class: 'ed-caption' }, 'Banii plătiți pe produsele păstrate, pe categorii, după reduceri: fiecare produs primește partea lui din voucherele și reducerile comenzii, proporțional cu prețul. Rândurile care nu sunt produse stau separat, ca toate rândurile să se adune exact la cât ai cheltuit. Regulile tale de categorii le pui în ', h('code', { class: 'ed-path', translate: 'no' }, 'config/categorii.personal.json'), ', pe care actualizarea îl păstrează.')
          : h('p', { class: 'ed-caption' }, 'Valoarea produselor păstrate (livrate sau ridicate și nereturnate), pe categorii. Regulile tale de categorii le pui în ', h('code', { class: 'ed-path', translate: 'no' }, 'config/categorii.personal.json'), ', pe care actualizarea îl păstrează.'),
        h('div', { class: 'ed-card' }, barsHost, tableHost));
    }

    function highlightsBlock(D) {
      const names = Object.keys(D.highlights);
      const title = highlightsTitle(names);
      const P = D.paid;
      const cards = names.map((name) => {
        const b = D.highlights[name], t = b.totals, items = b.items;
        const total = typeof b.items_total === 'number' ? b.items_total : items.length;
        const amount = (paidKey, listKey) => lei(P ? t[paidKey] : t[listKey]);
        const card = h('div', { class: 'ed-card ed-hl' },
          h(hTag(1), { class: 'ed-label' }, rich(name)),
          h('div', { class: 'ed-hl-num' }, h('span', { class: 'ed-hl-v' }, amount('paid_kept_bani', 'kept_bani')),
            h('span', { class: 'ed-hl-u' }, buc(t.kept_units) + (P ? ' păstrate, plătit după reduceri' : ' păstrate'))),
          h('p', { class: 'ed-hl-meta' }, 'Comandat: ' + buc(t.ordered_units) + ' (' + amount('paid_ordered_bani', 'ordered_bani') + ') · returnat: ' + buc(t.returned_units) + ' (' +
            amount('paid_returned_bani', 'returned_bani') + ') · anulat: ' + buc(t.cancelled_units) + ' (' + amount('paid_cancelled_bani', 'cancelled_bani') + ')' +
            ((P ? t.paid_pending_bani : t.pending_bani) ? ' · în curs: ' + amount('paid_pending_bani', 'pending_bani') : '')));
        if (items.length) {
          const head = [{ label: 'Data și comanda', nowrap: true }, { label: 'Produs', name: true }, { label: 'Buc', num: true },
            { label: P ? 'Plătit' : 'Valoare', num: true }, { label: 'Stare' }];
          card.appendChild(paged(items, (slice) => tableWrap(name, buildTable(name, head,
            slice.map((i) => [dateAndOrder(i.date, i.order_id, demoMode), productLink(i.name, i.order_id, 1, demoMode), int(i.qty),
              lei(P ? i.paid_amount_bani : i.amount_bani), pill(i.state)]), null, true))));
          if (total > items.length) card.appendChild(h('p', { class: 'ed-hl-meta' }, 'Primele ' + int(items.length) + ' din ' + int(total) + ' (vezi produse.csv pentru toate).'));
        } else card.appendChild(h('p', { class: 'ed-hl-meta' }, 'Niciun produs în această categorie.'));
        return card;
      });
      return block('highlights', title,
        heading(title),
        names.length ? h('div', { class: 'ed-hl-grid' }, cards) : emptyNote('Nicio categorie evidențiată în această rulare.'));
    }

    function yearsBlock(D) {
      const P = D.paid, F = D.funnel;
      const YC = P ? P.by_year_category : D.by_year_category;
      const years = YC.years, series = YC.series;
      const legend = h('div', { class: 'ed-legend' }, series.map((n, i) => h('span', { class: 'ed-legend-item' }, h('i', { class: 'ed-sw', 'aria-hidden': 'true', style: { background: seriesColor(n, i) } }), rich(n))));
      const chartHost = trackScroll(h('div', { class: 'ed-chart-scroll' }), 'Grafic pe ani, derulează orizontal dacă nu încape');
      const valueOf = (y, n) => {
        const row = hasOwn(YC.values, y) && isPlain(YC.values[y]) ? YC.values[y] : null;
        const v = row && hasOwn(row, n) ? row[n] : 0;
        return v > 0 ? v : 0;
      };
      const totals = years.map((y) => series.reduce((a, n) => a + valueOf(y, n), 0));
      let drawnWidth = -1;
      let hits = []; // coloanele focusabile ale desenului curent, în ordinea anilor

      function draw() {
        const avail = chartHost.clientWidth;
        if (avail === 0 && drawnWidth >= 0) return; // ascuns (se vede tabelul): păstrăm desenul de dinainte
        if (avail === drawnWidth) return;
        drawnWidth = avail;
        const rawMaxLei = Math.max(1, ...totals) / 100;
        const mag = Math.pow(10, Math.floor(Math.log10(rawMaxLei)));
        const step = Math.max(1, [1, 2, 5, 10].map((m) => m * mag).find((st) => rawMaxLei / st <= 5) || 10 * mag);
        const yMaxLei = Math.ceil(rawMaxLei / step) * step;
        // Marginea din stânga ține etichetele axei Y; cea mai lungă e valoarea maximă, deci se măsoară (nu se fixează):
        // pe un telefon fiecare pixel câștigat lasă mai mult loc coloanelor.
        const L = Math.max(36, Math.ceil(fmtInt(Math.round(yMaxLei)).length * CHART_LABEL_CHAR_PX) + 12), R = 12, T = 28, B = 34, H = 310;
        const W = Math.max(avail || CHART_DEFAULT_WIDTH, L + R + years.length * YEAR_SLOT_MIN);
        const pw = W - L - R, ph = H - T - B;
        const yPos = (bani) => T + ph - (bani / (yMaxLei * 100)) * ph;
        const svg = sv('svg', { class: 'ed-chart', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'group',
          'aria-label': P ? 'Bani plătiți pe ani, pe categorii' : 'Valoare păstrată pe ani, pe categorii' });
        for (let i = 0; i * step <= yMaxLei + 1e-6; i++) {
          const v = i * step;
          svg.appendChild(sv('line', { x1: L, x2: W - R, y1: yPos(v * 100), y2: yPos(v * 100), class: v === 0 ? 'ed-axis-line' : 'ed-grid-line', 'aria-hidden': 'true' }));
          svg.appendChild(sv('text', { x: L - 8, y: yPos(v * 100) + 4, 'text-anchor': 'end', 'aria-hidden': 'true' }, fmtInt(Math.round(v))));
        }
        svg.appendChild(sv('text', { x: L - 8, y: 14, 'text-anchor': 'end', 'aria-hidden': 'true' }, 'Lei'));
        const slot = pw / years.length, colW = Math.min(34, slot * 0.6);
        // Etichetele anilor se răresc când nu încap una lângă alta (ultimul an are mereu etichetă);
        // tooltip-ul și aria-label ale fiecărei coloane le au pe toate.
        const yearLabelStep = Math.max(1, Math.ceil((Math.max(...years.map((y) => clip(String(y), 12).length)) * CHART_LABEL_CHAR_PX + 6) / slot));
        const fresh = [];
        years.forEach((yr, idx) => {
          const cx = L + slot * idx + slot / 2;
          let acc = 0;
          series.forEach((n, si) => {
            const v = valueOf(yr, n);
            if (!v) return;
            const top = yPos(acc + v), bottom = yPos(acc);
            svg.appendChild(sv('rect', { x: cx - colW / 2, y: top, width: colW, height: Math.max(1, bottom - top - 2), style: { fill: seriesColor(n, si) }, 'aria-hidden': 'true' }));
            acc += v;
          });
          const totalLei = Math.round(totals[idx] / 100);
          let totalText = fmtInt(totalLei);
          if (totalText.length * 5.8 > slot - 2) totalText = totalLei >= 1e6 ? fmtOneDecimal(totalLei / 1e6) + ' M' : fmtInt(Math.round(totalLei / 1e3)) + ' k';
          svg.appendChild(sv('text', { x: cx, y: yPos(acc) - 6, 'text-anchor': 'middle', class: 'ed-total', 'aria-hidden': 'true' }, totalText));
          if ((years.length - 1 - idx) % yearLabelStep === 0) svg.appendChild(sv('text', { x: cx, y: H - 12, 'text-anchor': 'middle', 'aria-hidden': 'true' }, clip(String(yr), 12)));
          const rows = series.map((n, si) => ({ label: n, value: lei(valueOf(yr, n)), color: seriesColor(n, si), raw: valueOf(yr, n) }))
            .reverse().filter((r) => r.raw > 0);
          const hit = sv('rect', {
            x: L + slot * idx, y: T, width: slot, height: ph, class: 'ed-hit', tabindex: '0', role: 'img',
            'aria-label': yr + ': ' + lei(totals[idx]) + (rows.length ? ' (' + rows.slice().reverse().map((r) => r.label + ' ' + r.value).join(', ') + ')' : ''),
          });
          attachTip(hit, yr, rows.concat([{ label: 'Total', value: lei(totals[idx]) }]));
          fresh.push(hit);
          svg.appendChild(hit);
        });
        // Desenul nou înlocuiește coloanele (primul cadru după mount, apoi orice schimbare de lățime). Coloana cu focus
        // ar ieși din document: blur închide tooltip-ul și focusul cade pe <body>, deci următorul Tab o ia de la capăt.
        // Focusul trece pe coloana aceluiași an; tooltip-ul rămâne deschis doar dacă era (Escape îl închisese).
        const focused = hits.indexOf(chartHost.ownerDocument.activeElement);
        const tipWasOpen = focused >= 0 && tipTarget === hits[focused];
        chartHost.replaceChildren(svg);
        hits = fresh;
        if (focused >= 0) {
          hits[focused].focus({ preventScroll: true });
          if (!tipWasOpen) hideTip();
        }
      }

      const tableHost = h('div', { hidden: 'hidden' });
      const button = toggleButton();
      wireToggle(button, [chartHost, legend], tableHost, () => {
        const yrs = D.by_year;
        const head = [{ label: 'An' }, { label: 'Comenzi', num: true }, { label: 'Cu produse păstrate', num: true }, { label: 'Comandat', num: true },
          { label: 'Returnat', num: true }, { label: 'Anulat', num: true }, { label: P ? 'Plătit efectiv' : 'Păstrat', num: true }, { label: 'Buc păstrate', num: true }];
        const sum = (k) => yrs.reduce((a, r) => a + num(r[k]), 0);
        if (P) {
          const paidRows = yrs.map((r) => [r.year, int(r.orders), int(r.orders_with_kept), lei(r.paid_ordered_bani), lei(r.paid_returned_bani), lei(r.paid_cancelled_bani), lei(r.spent_bani), int(r.kept_units)]);
          return tableWrap('Pe ani', buildTable('Pe ani', head, paidRows, ['Total', int(sum('orders')), int(sum('orders_with_kept')), lei(sum('paid_ordered_bani')),
            lei(sum('paid_returned_bani')), lei(sum('paid_cancelled_bani')), lei(sum('spent_bani')), int(sum('kept_units'))]));
        }
        const rows = yrs.map((r) => [r.year, int(r.orders), int(r.orders_with_kept), lei(r.ordered_bani), lei(r.returned_bani), lei(r.cancelled_bani), lei(r.kept_bani), int(r.kept_units)]);
        return tableWrap('Pe ani', buildTable('Pe ani', head, rows, ['Total', int(sum('orders')), int(sum('orders_with_kept')), lei(F.ordered_bani), lei(F.returned_bani), lei(F.cancelled_bani), lei(F.kept_bani), int(F.kept_units)]));
      }, () => { drawnWidth = -1; scheduleLayout(); });

      redrawChart = years.length ? draw : null;
      const card = h('div', { class: 'ed-card' });
      if (years.length) card.append(legend, chartHost, tableHost);
      else card.append(emptyNote('Nu există date pe ani.'));
      const block1 = block('years', 'Pe ani',
        h('div', { class: 'ed-sec-head' }, heading('Pe ani'), years.length ? button : null),
        h('p', { class: 'ed-caption' }, P
          ? 'Banii plătiți efectiv, pe anul în care s-a plasat comanda, pe cele mai mari categorii. Transportul și taxele au seria lor dacă intră printre cele mai mari; altfel stau la „Altele”.'
          : 'Valoarea păstrată pe anul în care s-a plasat comanda, pe cele mai mari categorii.'),
        card);
      if (years.length) draw();
      return block1;
    }

    function bigBlock(D) {
      const P = D.paid, big = D.big, items = big.items;
      const total = (state) => lei(P ? big[state + '_paid_bani'] : big[state + '_bani']);
      const amountOf = (i) => (P ? i.paid_amount_bani : i.amount_bani);
      const title = 'Achiziții peste ' + lei(big.threshold_bani) + ' bucata';
      const caption = items.length
        ? count(items.length, 'linie de produs depășește', 'linii de produse depășesc') + ' pragul' + (P ? ' (prețul de listă pe bucată). Sumele sunt cele plătite, după reduceri.' : '.') +
          ' Păstrate: ' + buc(big.kept_units) + ' (' + total('kept') + '). Returnate: ' +
          buc(big.returned_units) + ' (' + total('returned') + '). Anulate: ' + buc(big.cancelled_units) + ' (' + total('cancelled') + ').'
        : 'Niciun produs nu depășește pragul.';
      const counts = new Map([['all', items.length]]);
      items.forEach((i) => counts.set(i.state, (counts.get(i.state) || 0) + 1));
      const FILTERS = [['all', 'Toate'], ['kept', 'Păstrate'], ['returned', 'Returnate'], ['cancelled', 'Anulate'], ['pending', 'În curs'], ['unknown', 'Necunoscute']]
        .filter((f) => counts.get(f[0]));
      const head = [{ label: 'Data și comanda', nowrap: true }, { label: 'Produs', name: true }, { label: 'Vânzător' }, { label: 'Categorie' },
        { label: P ? 'Preț de listă / buc' : 'Preț / buc', num: true }, { label: 'Buc', num: true }, { label: P ? 'Plătit' : 'Valoare', num: true }, { label: 'Stare' }];
      const host = h('div', { class: 'ed-stack', tabindex: '-1' });
      let current = 'all', limit = ROWS_PAGE;

      function render(focusMore) {
        const rows = items.filter((i) => current === 'all' || i.state === current);
        const shown = rows.slice(0, limit);
        const sumQty = rows.reduce((a, i) => a + num(i.qty), 0);
        const sumAmount = rows.reduce((a, i) => a + num(amountOf(i)), 0);
        const body = shown.map((i) => [dateAndOrder(i.date, i.order_id, demoMode), productLink(i.name, i.order_id, 1, demoMode), i.seller, i.category, lei(i.unit_bani), int(i.qty),
          lei(amountOf(i)), pill(i.state, i.returned_from_cancelled ? [' (marcat anulat de ', h('span', { translate: 'no' }, 'eMAG'), ')'] : null)]);
        const foot = ['', 'Total (' + count(rows.length, 'linie', 'linii') + ')', '', '', '', int(sumQty), lei(sumAmount), ''];
        const remaining = rows.length - shown.length;
        let more = null;
        if (remaining > 0) {
          more = moreButton(remaining);
          more.addEventListener('click', () => { limit += ROWS_PAGE; render(true); });
        }
        forgetScrollers(host); // tabelul vechi iese din evidență: altfel `scrollers` l-ar ține în memorie la fiecare clic
        host.replaceChildren(...[tableWrap(title, buildTable(title, head, body, foot, true)), more].filter(Boolean));
        if (focusMore) { if (more) more.focus({ preventScroll: true }); else host.focus({ preventScroll: true }); }
        refreshScrollers();
        announce('Se afișează ' + count(shown.length, 'linie', 'linii') + ' din ' + int(rows.length) + (current === 'all' ? '.' : ', filtru: ' + stateLabel(current) + '.'));
      }

      const chips = h('div', { class: 'ed-chips', role: 'group', 'aria-label': 'Filtrează după stare' });
      FILTERS.forEach((f) => {
        const b = h('button', { class: 'ed-chip', type: 'button', 'aria-pressed': String(f[0] === current) }, f[1] + ' (' + int(counts.get(f[0])) + ')');
        b.addEventListener('click', () => {
          current = f[0]; limit = ROWS_PAGE;
          Array.prototype.forEach.call(chips.children, (c) => c.setAttribute('aria-pressed', 'false'));
          b.setAttribute('aria-pressed', 'true');
          render(false);
        });
        chips.appendChild(b);
      });
      const out = block('big', title, heading(title), h('p', { class: 'ed-caption' }, caption));
      if (items.length) { out.append(chips, host); render(false); announce(''); }
      return out;
    }

    function topBlock(D) {
      const P = D.paid, rows = D.top_products;
      // Ordinea e după valoarea TOTALĂ păstrată pe produs (spend_analysis._top_products), nu după prețul pe bucată:
      // un produs ieftin cumpărat des poate trece înaintea unuia scump cumpărat o dată. Titlul spune asta.
      const title = 'Produse cu cea mai mare valoare păstrată';
      const head = [{ label: 'Produs', name: true }, { label: 'Categorie' }, { label: 'Buc', num: true }, { label: P ? 'Plătit' : 'Păstrat', num: true }];
      const linked = !demoMode && rows.some((p) => orderUrl(p.order_id) !== null);
      return block('top', title,
        heading(title),
        P || linked
          ? h('p', { class: 'ed-caption' }, rich((P ? 'Suma plătită pe fiecare produs păstrat, după reduceri, adunată pe toate comenzile lui.' : '') +
            (linked ? (P ? ' ' : '') + 'Numele duce la comanda lui cea mai recentă pe eMAG.' : '')))
          : null,
        rows.length
          ? paged(rows, (slice) => tableWrap(title, buildTable(title, head,
            slice.map((p) => [productLink(p.name, p.order_id, p.order_count, demoMode), p.category, int(p.units), lei(P ? p.paid_bani : p.bani)]), null, true)))
          : emptyNote('Nu există produse păstrate.'));
    }

    /* ----- Prețuri la același produs (cheia `price_history`, opțională) ----- */

    // Criteriile din „Ordonează după”: [cheie, text, comparator]. Departajarea la egalitate (ordinea din analiza.json) o face render().
    const PRICE_SORTS = [
      ['overpaid', 'Plătit peste minim (cel mai mult întâi)', (a, b) => num(b.overpaid_vs_min_bani) - num(a.overpaid_vs_min_bani)],
      ['rise', 'Cea mai mare scumpire la ultima cumpărare', (a, b) => num(b.last_vs_prev_unit_bani) - num(a.last_vs_prev_unit_bani)],
      ['drop', 'Cea mai mare ieftinire la ultima cumpărare', (a, b) => num(a.last_vs_prev_unit_bani) - num(b.last_vs_prev_unit_bani)],
      ['times', 'Cumpărări (cele mai multe întâi)', (a, b) => b.purchases.length - a.purchases.length],
      ['name', 'Nume (A–Z)', (a, b) => a.name.localeCompare(b.name, 'ro')],
    ];
    const plainMoney = (bani) => fmtMoney(num(bani) / 100);
    const noun = (n, one, many) => (n === 1 ? one : many);

    /** Diferența dintre ultimul preț pe bucată și cel dinainte, în cuvinte: „mai scump cu X Lei” / „mai ieftin cu X Lei” / „la fel”. */
    function priceChange(p) {
      const d = num(p.last_vs_prev_unit_bani);
      if (d === 0) return h('span', { class: 'ed-delta' }, 'la fel');
      const pc = p.last_vs_prev_pct;
      const percent = typeof pc === 'number'
        ? h('span', { class: 'ed-sub' }, (pc > 0 ? '+' : pc < 0 ? MINUS : '') + fmtOneDecimal(Math.abs(pc)) + NBSP + '%') : null;
      return [h('span', { class: 'ed-delta' }, h('span', { class: 'ed-arrow', 'aria-hidden': 'true' }, (d > 0 ? '▲' : '▼') + ' '),
        (d > 0 ? 'mai scump cu ' : 'mai ieftin cu ') + lei(Math.abs(d))), percent];
    }

    /** Tabelul cu istoricul unui produs: câte un rând pe cumpărare, cu numele din comandă, vânzătorul și linkul comenzii. */
    function priceHistoryTable(p) {
      const head = [{ label: 'Data', nowrap: true }, { label: 'Nume în comandă', name: true }, { label: 'Vânzător' }, { label: 'Buc', num: true },
        { label: 'Preț / buc', num: true }, { label: 'Comanda', nowrap: true }];
      const spread = p.min_unit_bani !== p.max_unit_bani;
      const rows = p.purchases.map((b) => {
        const tag = !spread ? null : b.unit_bani === p.min_unit_bani ? 'cel mai mic' : b.unit_bani === p.max_unit_bani ? 'cel mai mare' : null;
        return [fmtDate(b.date), productLink(b.name, b.order_id, 1, demoMode), b.seller, int(b.qty), [lei(b.unit_bani), tag ? h('span', { class: 'ed-sub' }, tag) : null],
          orderLink(b.order_id, demoMode)];
      });
      return buildTable('Istoricul prețurilor pentru ' + p.name, head, rows, null, true);
    }

    /** Rândul extensibil al unui produs (ascuns până la clic): tabelul cu istoric și, dacă e cazul, nota despre nume diferite. */
    function priceDetailRow(p, columns, open) {
      return h('tr', { class: 'ed-ph-detail', role: 'row', hidden: !open },
        h('td', { class: 'ed-ph-cell', role: 'cell', colspan: String(columns) },
          h('div', { class: 'ed-ph-inner' },
            h('p', { class: 'ed-caption' }, 'Cumpărările păstrate, de la cea mai veche la cea mai nouă. „Nume în comandă” e textul scris de vânzător în fiecare comandă.'),
            priceHistoryTable(p),
            p.color_variants === true
              ? h('p', { class: 'ed-note' }, 'Numele diferă între comenzi (de exemplu altă culoare): programul le ia drept același produs.')
              : null)));
    }

    function pricesBlock(D) {
      const PH = D.price_history;
      if (!PH) return null;
      const S = PH.summary, L = S.last_vs_prev;
      const title = 'Prețuri la același produs';
      const products = PH.products.filter((p) => p.purchases.length > 0).map((p, index) => ({ p, index, search: normalizeSearch(p.name) }));
      const out = block('preturi', title,
        heading(title),
        h('p', { class: 'ed-caption' }, 'Produsele păstrate din cel puțin două comenzi diferite, cu prețul pe bucată la fiecare cumpărare. „Același produs” înseamnă același model: culorile din nume nu contează.'));
      if (!products.length) {
        out.appendChild(emptyNote('Niciun produs n-a fost păstrat din cel puțin două comenzi diferite.'));
        return out;
      }
      const tiles = [
        { num: int(S.products), desc: noun(S.products, 'produs cumpărat', 'produse cumpărate') + ' în cel puțin două comenzi (' +
          count(S.purchases, 'cumpărare', 'cumpărări') + ', ' + buc(S.units) + ')' },
        { num: lei(S.overpaid_vs_min_bani), desc: 'plătit în plus față de cel mai mic preț al fiecărui produs (diferența față de minim, la bucățile păstrate)' },
        { num: int(L.pricier_products), desc: noun(L.pricier_products, 'produs la care ultimul preț e', 'produse la care ultimul preț e') +
          ' mai mare decât la cumpărarea dinainte: mai scump cu ' + lei(L.pricier_bani) + ' în total, la bucățile ultimei cumpărări' },
        { num: int(L.cheaper_products), desc: noun(L.cheaper_products, 'produs la care ultimul preț e', 'produse la care ultimul preț e') +
          ' mai mic: mai ieftin cu ' + lei(L.cheaper_bani) + ' în total' +
          (L.same_products ? '; la ' + count(L.same_products, 'produs', 'produse') + ' prețul e la fel' : '') },
      ];
      const tileList = h('ul', { class: 'ed-tiles ed-tiles-4', role: 'list' }, tiles.map((t) => h('li', { class: 'ed-tile' }, h('p', { class: 'ed-tile-num' }, t.num), h('p', { class: 'ed-tile-desc' }, t.desc))));

      let query = '', sortKey = PRICE_SORTS[0][0], limit = PRICE_ROWS_PAGE;
      const opened = new Set(); // produsele cu istoricul deschis: rămân deschise după filtrare, sortare sau „Arată încă”
      const search = h('input', { class: 'ed-input', type: 'search', name: 'cauta-produs', autocomplete: 'off', spellcheck: 'false', placeholder: 'de ex. cafea…' });
      const sort = h('select', { class: 'ed-input', name: 'ordine-produse' }, PRICE_SORTS.map((s) => h('option', { value: s[0] }, s[1])));
      const tools = h('div', { class: 'ed-tools' },
        h('label', { class: 'ed-field' }, h('span', { class: 'ed-field-label' }, 'Caută produs'), search),
        h('label', { class: 'ed-field' }, h('span', { class: 'ed-field-label' }, 'Ordonează după'), sort));
      const status = h('p', { class: 'ed-note' });
      const host = h('div', { class: 'ed-stack', tabindex: '-1' });
      const head = [{ label: 'Produs', name: true }, { label: 'Cumpărări', num: true }, { label: 'Primul preț (Lei)', num: true }, { label: 'Ultimul preț (Lei)', num: true },
        { label: 'Preț minim (Lei)', num: true }, { label: 'Preț maxim (Lei)', num: true }, { label: 'Ultimul preț față de precedentul' },
        { label: 'Plătit peste minim', num: true }, { label: 'Evoluție' }];
      let found = products.length;

      function statusText() {
        return count(found, 'produs', 'produse') + (found < products.length ? ' din ' + int(products.length) : '') +
          (query.trim() ? ', căutare: „' + clip(query.trim(), 30) + '”.' : '.');
      }

      function render(focusMore) {
        const terms = normalizeSearch(query).split(' ').filter(Boolean);
        const compare = PRICE_SORTS.filter((s) => s[0] === sortKey)[0][2];
        const rows = products.filter((e) => terms.every((t) => e.search.indexOf(t) >= 0)).sort((a, b) => compare(a.p, b.p) || a.index - b.index);
        const shown = rows.slice(0, limit);
        found = rows.length;
        status.textContent = statusText();
        // Săgeata deschide istoricul (buton separat); numele e link spre comanda cea mai recentă a produsului (cumpărările sunt cronologice).
        const buttons = shown.map(({ p }) => h('button', { class: 'ed-ph-open', type: 'button', 'aria-expanded': 'false' },
          h('span', { class: 'ed-chev', 'aria-hidden': 'true' }, '▸'),
          h('span', { class: 'ed-sr' }, 'Arată istoricul prețurilor: ' + p.name)));
        let table = null;
        if (shown.length) {
          const body = shown.map(({ p }, i) => [
            [h('div', { class: 'ed-ph-name' }, buttons[i], h('span', { class: 'ed-pname' },
              productLink(p.name, p.purchases[p.purchases.length - 1].order_id, new Set(p.purchases.map((b) => b.order_id)).size, demoMode))),
            p.category ? h('span', { class: 'ed-sub' }, rich(p.category)) : null],
            [int(p.purchases.length), h('span', { class: 'ed-sub' }, buc(p.kept_units))],
            plainMoney(p.first_unit_bani), plainMoney(p.last_unit_bani), plainMoney(p.min_unit_bani), plainMoney(p.max_unit_bani),
            priceChange(p), lei(p.overpaid_vs_min_bani), sparkline(p)]);
          table = buildTable(title, head, body, null, true, 'ed-tbl-prices');
          Array.prototype.slice.call(table.tBodies[0].rows).forEach((tr, i) => {
            const p = shown[i].p, button = buttons[i];
            let detail = null;
            const sync = () => {
              const isOpen = opened.has(p.key);
              button.setAttribute('aria-expanded', String(isOpen));
              button.firstChild.textContent = isOpen ? '▾' : '▸';
              if (isOpen && !detail) { detail = priceDetailRow(p, head.length, true); tr.after(detail); }
              if (detail) detail.hidden = !isOpen;
            };
            button.addEventListener('click', () => {
              if (opened.has(p.key)) opened.delete(p.key); else opened.add(p.key);
              sync();
              refreshScrollers();
              announce(opened.has(p.key) ? 'Istoricul prețurilor e afișat.' : 'Istoricul prețurilor e ascuns.');
            });
            sync();
          });
        }
        const remaining = rows.length - shown.length;
        let more = null;
        if (remaining > 0) {
          more = moreButton(remaining, PRICE_ROWS_PAGE);
          more.addEventListener('click', () => { limit += PRICE_ROWS_PAGE; render(true); });
        }
        forgetScrollers(host);
        host.replaceChildren(...[table ? tableWrap(title, table) : emptyNote('Niciun produs nu se potrivește cu căutarea.'), more].filter(Boolean));
        if (focusMore) { if (more) more.focus({ preventScroll: true }); else host.focus({ preventScroll: true }); }
        refreshScrollers();
      }

      search.addEventListener('input', () => {
        query = search.value;
        limit = PRICE_ROWS_PAGE;
        render(false);
        global.clearTimeout(announceTimer);
        announceTimer = global.setTimeout(() => { if (mounted) announce(statusText()); }, ANNOUNCE_DELAY_MS);
      });
      sort.addEventListener('change', () => {
        sortKey = sort.value;
        limit = PRICE_ROWS_PAGE;
        render(false);
        announce('Ordonat după: ' + PRICE_SORTS.filter((s) => s[0] === sortKey)[0][1] + '.');
      });

      out.append(tileList, tools, status, host,
        h('p', { class: 'ed-note ed-ph-limits' }, rich('Cum se citește: prețurile sunt cele din comenzi, pe bucată, înainte de vouchere: aici se compară prețul de listă, nu suma plătită ' +
          '(aceea e în restul raportului). Pot include promoții și pot veni de la vânzători diferiți ' +
          '(eMAG sau marketplace), deci o diferență arată cum s-a schimbat prețul plătit, nu dacă oferta a fost bună sau proastă. Culorile din nume se ignoră ' +
          '(același model în alb și în negru e același produs); capacitatea sau dimensiunea (de exemplu 128 GB, 55 inch) nu se ignoră: sunt produse diferite.')));
      render(false);
      return out;
    }

    function sellersBlock(D) {
      const P = D.paid, sellers = D.by_seller;
      const total = P ? P.products_kept_bani : D.funnel.kept_bani;
      return block('sellers', 'Vânzători',
        heading('Vânzători'),
        h('p', { class: 'ed-caption' }, rich(P
          ? 'Banii plătiți pe produsele păstrate, pe vânzător (eMAG sau vânzători din marketplace), după reduceri; fără transport și taxe.'
          : 'Valoarea păstrată pe vânzător (eMAG sau vânzători din marketplace).')),
        h('div', { class: 'ed-card' }, sellers.length
          ? barList(sellers.map((x) => ({
            name: x.seller, bani: P ? x.paid_bani : x.bani, units: x.units,
            tip: (P ? [{ label: 'Plătit', value: lei(x.paid_bani) }, { label: 'La preț de listă', value: lei(x.bani) }] : [{ label: 'Păstrat', value: lei(x.bani) }])
              .concat([{ label: 'Bucăți', value: buc(x.units) }]),
          })), total)
          : emptyNote('Nu există vânzători de afișat.')));
    }

    /** Numele produselor unui bloc, fiecare ca link spre comanda blocului, despărțite prin „; ”. */
    function productNames(names, orderId) {
      return names.map((name, i) => [i ? '; ' : null, productLink(name, orderId, 1, demoMode)]);
    }

    function excludedBlock(D) {
      const rows = D.paid_only.map((b) => ['Plătit fără livrare', dateAndOrder(b.date, b.order_id, demoMode), b.seller, productNames(b.names, b.order_id), lei(b.paid_bani)])
        .concat(D.in_progress.map((b) => ['În curs', dateAndOrder(b.date, b.order_id, demoMode), b.seller, productNames(b.names, b.order_id), lei(b.paid_bani)]));
      const title = 'Rămase în afara calculului';
      const head = [{ label: 'Tip', nowrap: true }, { label: 'Data și comanda', nowrap: true }, { label: 'Vânzător' }, { label: 'Produse', name: true },
        { label: 'Plătit', num: true }];
      return block('excluded', title,
        heading(title),
        h('p', { class: 'ed-caption' }, 'Plătite fără livrare de produse (asigurări) sau încă nelivrate. Nu intră în cât ai cheltuit.'),
        rows.length
          ? paged(rows, (slice) => tableWrap(title, buildTable(title, head, slice, null, true)))
          : emptyNote('Nimic de raportat aici.'));
    }

    /** Rândurile unei grupe de avertismente: data, detaliul, vânzătorul și linkurile spre comanda (și returul) de pe eMAG. */
    function warningRows(items) {
      return items.map((it) => {
        const links = it.order_ids.map((id) => orderLink(id, demoMode));
        if (typeof it.return_id === 'string') links.push(returnLink(it.return_id, it.return_url, demoMode));
        return [fmtDate(it.placed_at), it.text, it.seller || '', h('div', { class: 'ed-links' }, links.map((l) => h('span', null, l)))];
      });
    }
    /**
     * O grupă de avertismente ca `<details>`: titlul, câte cazuri are și dacă schimbă totalurile se văd închis;
     * deschisă arată ce înseamnă, ce faci și comenzile concrete, fiecare cu link spre eMAG. Textele vin din
     * config/avertismente.json (prin analiza.json), nu din cod.
     */
    function warningGroup(g) {
      const head = [{ label: 'Data', nowrap: true }, { label: 'Detaliu', name: true }, { label: 'Vânzător' }, { label: 'Comanda' }];
      const affects = g.affects_totals === true;
      const shownCount = Math.max(num(g.count), g.items.length);
      return h('details', { class: 'ed-wg', 'data-affects': String(affects) },
        h('summary', { class: 'ed-wg-sum' },
          h('span', { class: 'ed-wg-title' }, rich(g.title)),
          h('span', { class: 'ed-wg-meta' },
            h('span', null, count(shownCount, 'caz', 'cazuri')),
            h('span', { class: 'ed-wg-aff' }, 'Afectează totalurile: ' + (affects ? 'da' : 'nu')))),
        h('div', { class: 'ed-wg-body' },
          h('p', { class: 'ed-wg-text' }, rich(g.explanation)),
          h('p', { class: 'ed-wg-text' }, h('strong', null, 'Ce faci: '), rich(g.what_to_do)),
          g.items.length
            ? paged(g.items, (slice) => tableWrap(g.title, buildTable(g.title, head, warningRows(slice), null, true)))
            : emptyNote('Niciun rând de afișat.')));
    }
    /** Toate grupele de avertismente, cu o introducere scurtă: cum se deschid și ce găsești în ele. */
    function warningGroups(groups) {
      const cases = groups.reduce((sum, g) => sum + Math.max(num(g.count), g.items.length), 0);
      return h('div', { class: 'ed-wgroups' },
        heading('Avertismente de verificat', 1, 'ed-h-sub'),
        h('p', { class: 'ed-caption' }, count(groups.length, 'grup', 'grupe') + ', ' + count(cases, 'caz', 'cazuri') +
          '. ', rich('Deschide un grup ca să vezi ce înseamnă, dacă îți schimbă totalurile, ce faci și comenzile la care se referă, cu link către eMAG.')),
        groups.map(warningGroup));
    }

    /** Reconcilierea plătitului efectiv cu „Total plătit” al comenzilor livrate (rânduri cheie-valoare); estimările sunt numite. */
    function paidCheckRows(P) {
      const C = P.reconciliation;
      const rows = [['Total plătit eMAG, comenzi livrate/ridicate', lei(C.paid_delivered_bani)]];
      if (C.rebuilt_blocks) rows.push(['din care calculat din componente (' + count(C.rebuilt_blocks, 'bloc', 'blocuri') + ' fără „Total plătit”)', lei(C.rebuilt_bani)]);
      rows.push([MINUS + ' bani primiți înapoi la retururi', lei(C.cash_refunds_bani) + (C.estimated_refunds
        ? ' (din care estimat ' + lei(C.estimated_refunds_bani) + ', ' + count(C.estimated_refunds, 'retur', 'retururi') + ' fără sumă afișată)' : ''), !!C.estimated_refunds]);
      if (C.credit_returns_added_bani) rows.push(['+ retururi cu voucher sau sold, din comenzi marcate „anulat”', lei(C.credit_returns_added_bani)]);
      rows.push(['= Plătit efectiv', lei(C.spent_bani)]);
      return rows;
    }

    function controlBlock(D) {
      const R = D.reconciliation, M = D.meta, W = D.warnings, P = D.paid;
      const kv = (P ? paidCheckRows(P) : [['Total plătit eMAG, comenzi livrate/ridicate', lei(R.paid_delivered_bani)]]).concat([
        ['din care vouchere și reduceri', lei(R.vouchers_delivered_bani)],
        ['din care transport', lei(R.shipping_delivered_bani)],
        ['din care servicii și taxe', lei(R.services_delivered_bani)],
        ['Cereri de retur', int(R.returns_total)],
        ['Retururi finalizate', int(R.returns_completed) + ' (restituit ' + lei(R.refunds_bani) + ')'],
        ['Retururi anulate', int(R.returns_cancelled)],
        ['Retururi fără rezultat', int(R.returns_pending)],
        ['Produse returnate potrivite cu comenzi', buc(D.returns.matched_units)],
        ['din care marcate „anulat” de eMAG', buc(D.returns.matched_from_cancelled_units)],
        ['Comenzi cu factură storno', int(R.orders_with_storno.length)],
        ['Comenzi analizate / blocuri / produse', int(M.orders) + ' / ' + int(M.blocks) + ' / ' + int(M.lines)],
      ]);
      if (P) {
        const C = P.reconciliation;
        kv.push(['La preț de listă, înainte de reduceri: comandat / păstrat', lei(D.funnel.ordered_bani) + ' / ' + lei(D.funnel.kept_bani), true]);
        kv.push(['În afara calculului: în curs / plătite fără livrare', lei(C.in_progress_bani) + ' / ' + lei(C.paid_only_bani), true]);
      }
      const modes = R.refund_modes ? Object.keys(R.refund_modes) : [];
      if (modes.length) kv.push(['Moduri de restituire', modes.map((k) => k + ': ' + int(R.refund_modes[k])).join(' · '), true]);
      const grid = h('dl', { class: 'ed-kv' }, kv.map((r) => h('div', null, h('dt', null, rich(r[0])), h('dd', { class: r[2] ? 'ed-long' : null }, rich(r[1])))));

      const stack = h('div', { class: 'ed-details-stack' });
      if (D.warnings_detail && D.warnings_detail.length) {
        // Raport nou: avertismentele pe grupe, cu comenzile concrete. Lista de texte `warnings` rămâne în analiza.json
        // și în rezumat.txt; aici ar repeta aceleași lucruri mai prost.
        stack.appendChild(warningGroups(D.warnings_detail));
      } else if (W.length) {
        // Raport vechi (fără `warnings_detail`): lista simplă de texte, ca înainte. Numerele de comandă din ea
        // rămân text: nu le căutăm în fraze libere ca să facem linkuri, fiindcă o potrivire greșită ar duce la altă comandă.
        const items = W.slice(0, WARNINGS_SHOWN).map((w) => h('li', null, rich(w)));
        if (W.length > WARNINGS_SHOWN) items.push(h('li', null, '… și încă ' + int(W.length - WARNINGS_SHOWN) + ' (le găsești în analiza.json).'));
        stack.appendChild(h('details', null, h('summary', null, count(W.length, 'avertisment', 'avertismente') + ' de verificat'), h('ul', null, items)));
      } else {
        stack.appendChild(h('p', { class: 'ed-status' }, h('i', { class: 'ed-sw', 'aria-hidden': 'true' }), 'Niciun avertisment: verificările interne de sume au trecut.'));
      }
      if (D.uncategorized.length) {
        const shown = D.uncategorized.slice(0, UNCATEGORIZED_SHOWN);
        const more = D.uncategorized_count > shown.length ? ' (primele ' + int(shown.length) + ')' : '';
        stack.appendChild(h('details', null,
          h('summary', null, count(D.uncategorized_count, 'produs necategorizat', 'produse necategorizate') + more),
          h('p', { class: 'ed-caption ed-after-summary' }, 'Adaugă reguli în ', h('code', { class: 'ed-path', translate: 'no' }, 'config/categorii.personal.json'), ' și refă raportul cu ', h('code', { translate: 'no' }, '--din-cache'), '.'),
          tableWrap('Produse necategorizate', buildTable('Produse necategorizate',
            [{ label: 'Produs', name: true }, { label: 'Buc', num: true }, { label: 'Valoare', num: true }],
            shown.map((u) => [productLink(u.name, u.order_id, u.order_count, demoMode), int(u.units), lei(u.bani)]), null, true))));
      }
      return block('control', 'Cifre de control',
        heading('Cifre de control'),
        h('div', { class: 'ed-card' }, grid),
        stack);
    }

    function methodBlock(D) {
      if (D.paid) return paidMethodBlock(D);
      return block('method', 'Cum se calculează',
        heading('Cum se calculează'),
        h('div', { class: 'ed-method' },
          h('p', null, h('strong', null, 'Cum se calculează. '), rich('Comandat = valoarea tuturor produselor din comenzi. Păstrat = comandat minus anulat, returnat și cele încă nelivrate. Un retur finalizat se numără ca returnat, nu ca anulare. Pe paginile observate la scrierea programului, produsele vândute de eMAG și returnate rămân în comandă cu factură storno, iar la vânzătorii din marketplace eMAG marchează returul „Livrare anulată”; dacă la contul tău apare altfel, verifică în cont cifrele de la retururi.')),
          h('p', null, h('strong', null, 'Ce nu intră. '), 'Asigurările plătite fără livrare de produse, comenzile în curs și returnările fără pasul „Restituire sumă” (cererea rămâne doar înregistrată sau anulată; produsul rămâne numărat ca păstrat). Un status necunoscut nu e numărat niciodată ca livrat.'),
          h('p', null, h('strong', null, 'Prețuri. '), rich('Sumele pe produs sunt cele afișate de eMAG înainte de vouchere. Voucherele, transportul și taxele sunt în cifrele de control.')),
          h('p', null, h('strong', null, 'Achiziție mare. '), 'Un produs cu prețul pe bucată strict peste ' + lei(D.meta.threshold_bani) + '. Pragul se schimbă cu ', h('code', { translate: 'no' }, '--prag'), ' la rulare.')));
    }

    /** Nota de metodă a unui raport cu `paid`: regulile banilor plătiți, ale retururilor și ce rămâne la preț de listă. */
    function paidMethodBlock(D) {
      return block('method', 'Cum se calculează',
        heading('Cum se calculează'),
        h('div', { class: 'ed-method' },
          h('p', null, h('strong', null, 'Cât ai cheltuit. '), rich('Suma „Total plătit” a fiecărei comenzi livrate sau ridicate (după vouchere, card cadou și reduceri, cu transportul și taxele), minus banii primiți înapoi la retururi. O comandă fără „Total plătit” afișat se calculează din componentele ei: produse, reduceri, transport, taxe.')),
          h('p', null, h('strong', null, 'Pe produse. '), rich('Fiecare produs primește partea lui din reducerile comenzii, proporțional cu prețul lui, în bani întregi; așa restituie și eMAG la retur. Transportul și taxele nu se împart pe produse: au rândul lor, „Transport și taxe”, ca rândurile de la categorii să se adune exact la cât ai cheltuit.')),
          h('p', null, h('strong', null, 'Retururi. '), rich('Un retur finalizat se numără ca returnat, nu ca anulare. Cu bani înapoi: se scade suma restituită afișată; dacă pagina nu o arată, partea plătită a produsului (estimare, numărată la cifrele de control). Cu voucher sau sold eMAG: nu se scade nimic, fiindcă voucherul scade deja „Total plătit” al comenzii în care îl folosești; scăzut și aici, ar fi scăzut de două ori. Pe paginile observate la scrierea programului, produsele vândute de eMAG și returnate rămân în comandă cu factură storno, iar la vânzătorii din marketplace eMAG marchează returul „Livrare anulată”: acolo plata și restituirea se anulează reciproc, iar un astfel de retur cu voucher se adaugă o singură dată, la „Retururi cu voucher sau sold eMAG”. Dacă la contul tău apare altfel, verifică în cont cifrele de la retururi. Modurile de restituire se pot edita în '),
            h('code', { translate: 'no' }, 'config/restituiri.json'), '.'),
          h('p', null, h('strong', null, 'Ce nu intră. '), 'Comenzile anulate, cele în curs, asigurările plătite fără livrare de produse și returnările fără pasul „Restituire sumă” (cererea rămâne doar înregistrată sau anulată; produsul rămâne numărat ca păstrat). Un status necunoscut nu e numărat niciodată ca livrat.'),
          h('p', null, h('strong', null, 'Prețuri de listă. '), 'Pragul pentru „achiziție mare” (strict peste ' + lei(D.meta.threshold_bani) + ' pe bucată, se schimbă cu ', h('code', { translate: 'no' }, '--prag'),
            ') și „Prețuri la același produs” folosesc prețul de listă pe bucată: sunt comparații de preț, nu de bani plătiți.')));
    }

    /* ---------- stare de eroare: date lipsă sau greșite ---------- */
    function renderError(errors) {
      const list = errors.map((e) => h('li', null, e));
      root.appendChild(h('div', { class: 'ed-wrap' }, h('section', { class: 'ed-card ed-error', role: 'alert' },
        heading('Nu pot afișa raportul'),
        h('p', { class: 'ed-note' }, 'Datele primite nu au forma pe care o așteaptă raportul:'),
        h('ul', { class: 'ed-error-list' }, list),
        h('p', { class: 'ed-hint' }, 'Alege din nou fișierul analiza.json din folderul unei rulări (iesiri\\<data>_<ora>\\) sau refă rularea din aplicația locală.'))));
    }

    function renderReport(data) {
      const D = withDefaults(data);
      // pricesBlock întoarce null când analiza.json n-are cheia `price_history` (raport vechi): blocul pur și simplu lipsește.
      const blocks = [heroBlock, funnelBlock, tilesBlock, categoriesBlock, highlightsBlock, yearsBlock, bigBlock, topBlock, pricesBlock, sellersBlock, excludedBlock, controlBlock, methodBlock]
        .map((build) => build(D)).filter(Boolean);
      wrap = h('div', { class: 'ed-wrap' }, blocks);
      root.appendChild(wrap);
    }

    function clearRoot() { while (root.firstChild) root.removeChild(root.firstChild); }

    function render(data) {
      addedClass = !root.classList.contains('emag-dash');
      root.classList.add('emag-dash');
      root.setAttribute('data-ed-version', VERSION);
      clearRoot();
      demoMode = opts.demo === true || !!(data && data.meta && typeof data.meta === 'object' && data.meta.demo === true);
      if (demoMode) root.appendChild(h('div', { class: 'ed-banner', role: 'note' }, 'Date de demonstrație, inventate. Nu sunt comenzile nimănui.'));
      tip = h('div', { class: 'ed-tip', role: 'tooltip', hidden: 'hidden' });
      live = h('p', { class: 'ed-sr', role: 'status', 'aria-live': 'polite' });
      const check = validate(data);
      self.ok = check.ok;
      self.errors = check.errors;
      root.setAttribute('data-ed-state', check.ok ? 'ready' : 'error');
      if (!check.ok) {
        renderError(check.errors);
      } else {
        try {
          renderReport(data);
        } catch (err) {
          // Bug de desenare pe date neașteptate: arătăm eroarea în loc de o pagină pe jumătate goală.
          self.ok = false;
          self.errors = ['Nu am putut desena raportul din aceste date. Încearcă să refaci rularea din aplicația locală.'];
          root.setAttribute('data-ed-state', 'error');
          clearRoot();
          if (demoMode) root.appendChild(h('div', { class: 'ed-banner', role: 'note' }, 'Date de demonstrație, inventate. Nu sunt comenzile nimănui.'));
          wrap = null; redrawChart = null; scrollers.length = 0;
          renderError(self.errors);
          if (global.console && global.console.error) global.console.error('EmagDashboard: eroare la desenare', err);
        }
      }
      root.append(tip, live);
      listen(root, 'keydown', (e) => { if (e.key === 'Escape') hideTip(); });
      listen(global, 'scroll', onScroll, { passive: true, capture: true });
      if (wrap && typeof global.ResizeObserver === 'function') {
        observer = new global.ResizeObserver(scheduleLayout);
        observer.observe(wrap);
      }
      seenConnected = root.isConnected;
      scheduleLayout();
    }

    function unmount() {
      if (!mounted) return;
      mounted = false;
      listeners.forEach((l) => l[0].removeEventListener(l[1], l[2], l[3]));
      listeners.length = 0;
      if (observer) observer.disconnect();
      if (frame) global.cancelAnimationFrame(frame);
      global.clearTimeout(announceTimer);
      clearRoot();
      if (addedClass) root.classList.remove('emag-dash');
      if (!root.getAttribute('class')) root.removeAttribute('class');
      root.removeAttribute('data-ed-state');
      root.removeAttribute('data-ed-version');
      if (INSTANCES.get(root) === self) INSTANCES.delete(root);
    }

    self.render = render;
    self.unmount = unmount;
    return self;
  }

  /**
   * Desenează raportul în `root`. Nu aruncă pe date greșite: arată o stare de eroare.
   * Singura excepție: `root` care nu e un element (greșeală de programare, nu de date).
   */
  function mount(root, data, options) {
    if (!root || root.nodeType !== 1) throw new TypeError('EmagDashboard.mount: primul argument trebuie să fie un element HTML.');
    const previous = INSTANCES.get(root);
    if (previous) previous.unmount();
    const inst = createInstance(root, options);
    INSTANCES.set(root, inst);
    inst.render(data);
    return { unmount: inst.unmount, root, ok: inst.ok, errors: inst.errors.slice() };
  }

  global.EmagDashboard = { version: VERSION, validate, mount };
})(typeof window !== 'undefined' ? window : this);

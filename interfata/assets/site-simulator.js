/* site-simulator.js — simulatorul „Cum se calculează”: comenzi inventate, stări comutabile, lanț recalculat live.
 * Primește: nimic din afară, în afară de pragul implicit din datele demo (window.EMAG_DEMO_DATA.big.threshold_bani).
 * Dă înapoi: nimic; desenează comenzile, lanțul comandat → plătit și regula activă într-un panou aria-live.
 * Starea unei comenzi NU e o etichetă ținută în JS: se alege ce afișează eMAG (text de status, pași de retur),
 * iar rezultatul se deduce cu aceleași reguli ca programul (oglindă a emag_spend/block_status.py și
 * return_matcher.py). Dacă acele reguli se schimbă în Python, actualizează STATUS_RULES de aici;
 * tests/test_site_static.py pică dacă lista nu mai coincide.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  var FALLBACK_THRESHOLD_LEI = 500; // folosit doar dacă datele demo lipsesc; în mod normal pragul vine din ele
  var MAX_THRESHOLD_LEI = 1000000; // peste un milion de lei pe bucată pragul n-are sens; evită „∞” și numere de 20 de cifre

  /** Frazele de status, în ordinea din block_status._RULES (prima potrivire câștigă). Text fără diacritice. */
  var STATUS_RULES = [
    ['livrare anulata', 'CANCELLED'],
    ['produse ridicate', 'DELIVERED'],
    ['produse livrate', 'DELIVERED'],
    ['plata acceptata', 'PAID_ONLY'],
    ['comanda plasata', 'IN_PROGRESS'],
    ['predate curierului', 'IN_PROGRESS'],
    ['in drum spre', 'IN_PROGRESS'],
    ['ajunse in', 'IN_PROGRESS'],
    ['ajunse la', 'IN_PROGRESS'],
    ['in curs de', 'IN_PROGRESS'],
    ['in pregatire', 'IN_PROGRESS'],
    ['pregatit', 'IN_PROGRESS'],
    ['expediat', 'IN_PROGRESS'],
    ['confirmat', 'IN_PROGRESS']
  ];
  var START_STATE = { DELIVERED: 'kept', CANCELLED: 'cancelled', IN_PROGRESS: 'pending', UNKNOWN: 'unknown', PAID_ONLY: 'paidonly' };
  var RETURN_STEP = 'restituire suma'; // pasul care face un retur „finalizat” când are dată

  /** Ce poate afișa eMAG pentru o comandă: textul de status al blocului și (opțional) pașii returului. */
  var SCENARIOS = [
    { id: 'delivered', label: 'Livrat', status: 'Produse livrate', steps: null },
    { id: 'returned', label: 'Retur finalizat', status: 'Produse livrate', steps: [['Recepționare produs', true], ['Restituire sumă', true]] },
    { id: 'requested', label: 'Retur doar cerut', status: 'Produse livrate', steps: [['Recepționare produs', false], ['Restituire sumă', false]] },
    { id: 'cancelled', label: 'Anulat', status: 'Livrare anulată', steps: null },
    { id: 'pending', label: 'În curs', status: 'Predate curierului', steps: null },
    { id: 'marketplace', label: 'Marketplace: „Livrare anulată” după retur', status: 'Livrare anulată', steps: [['Recepționare produs', true], ['Restituire sumă', true]] },
    { id: 'unknown', label: 'Status nou, necunoscut', status: 'Livrare suspendată temporar', steps: null, invented: true }
  ];

  /** Explicația fiecărui scenariu: regula, ce decide și unde stă în cod. */
  var EXPLAIN = {
    delivered: { rule: 'Blocul are statusul „Produse livrate” sau „Produse ridicate”: produsul pornește ca păstrat.', where: 'emag_spend/block_status.py (_RULES) și line_ledger.py' },
    returned: { rule: 'Returul e finalizat: pasul „Restituire sumă” are dată. Câte o unitate din „păstrat”, pentru fiecare apariție a numelui în retur, trece în „returnat”, iar suma ei se scade din total.', where: 'emag_spend/return_parser.py (completed) și return_matcher.py (apply_returns)' },
    requested: { rule: 'Cererea de retur există, dar pasul „Restituire sumă” nu are dată: returul nu e finalizat, deci produsul rămâne păstrat. Raportul avertizează: „N retururi cu cerere înregistrată dar fără rezultat…”.', where: 'emag_spend/return_parser.py (doar pașii cu dată contează) și spend_analysis.py (avertisment)' },
    cancelled: { rule: 'Statusul conține „Livrare anulată” și nu există retur finalizat: produsul e anulat. Fraza „Livrare anulată” are prioritate față de orice altă frază din bloc.', where: 'emag_spend/block_status.py (prima regulă din _RULES)' },
    pending: { rule: 'Statusul spune că produsul n-a ajuns încă la tine (plasată, predată curierului, în drum, ajunsă la punctul de ridicare dar încă neridicată…): e „în curs” și nu se numără ca păstrat până nu apare „Produse livrate” sau „Produse ridicate”.', where: 'emag_spend/block_status.py (regulile IN_PROGRESS)' },
    marketplace: { rule: 'La vânzătorii din marketplace, eMAG arată „Livrare anulată” și pentru un produs returnat. Fiindcă există retur finalizat, unitățile „anulate” (câte una pentru fiecare apariție a numelui în retur) devin „returnate”: nu se numără ca anulare și nu se scad de două ori.', where: 'emag_spend/return_matcher.py (returned_from_cancelled_qty)' },
    unknown: { rule: 'Textul de status nu se potrivește cu nicio frază cunoscută: starea e „necunoscut”. Produsul NU e numărat ca livrat; stă separat în lanț și apare avertismentul „status necunoscut la comanda …”.', where: 'emag_spend/block_status.py (UNKNOWN) și spend_analysis.py (avertisment)' }
  };

  /** Comenzile inventate. `unit` e prețul pe bucată în BANI. Nume și numere sunt fictive. */
  var ORDERS = [
    { id: 'D-01', seller: 'eMAG', name: 'Aspirator vertical Vexa V8', unit: 89900, qty: 1, initial: 'delivered' },
    { id: 'D-02', seller: 'eMAG', name: 'Căști fără fir Brisa', unit: 50000, qty: 1, initial: 'returned' },
    { id: 'D-03', seller: 'Atelier Lumen (marketplace)', name: 'Lampă de birou Lumen', unit: 18900, qty: 2, initial: 'marketplace' },
    { id: 'D-04', seller: 'eMAG', name: 'Set de cuțite Serra, 6 piese', unit: 24900, qty: 1, initial: 'cancelled' },
    { id: 'D-05', seller: 'eMAG', name: 'Monitor Aurel 27 inch', unit: 129900, qty: 1, initial: 'pending' },
    { id: 'D-06', seller: 'eMAG', name: 'Rucsac Sendero 30 L', unit: 21900, qty: 1, initial: 'requested' }
  ];
  // Eticheta totalului e scurtă („= Plătit”, ca pe bonul din hero): „Plătit efectiv” ar rupe rândul în două la lățimi obișnuite.
  var CHAIN_ROWS = [
    ['ordered', 'Comandat în total', ''], ['cancelled', 'Anulat', '− '], ['returned', 'Returnat', '− '],
    ['pending', 'În curs', '− '], ['unknown', 'Necunoscut', '− '], ['kept', 'Plătit', '= ']
  ];

  var state = {}; // id comandă -> id scenariu ales
  var els = {};
  var lastChanged = ORDERS[0].id;
  var ruleKey = ''; // comanda + scenariul pentru care e desenată regula activă (nu se rescrie dacă nu s-a schimbat)

  /** Text fără diacritice, litere mici, spații unice (ca emag_spend/text_normalize.normalize_text). */
  function normalize(text) {
    return String(text).normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  /** Clasa unui text de status și regula care a potrivit: { cls, index, needle }. */
  function classify(statusText) {
    var text = normalize(statusText);
    for (var i = 0; i < STATUS_RULES.length; i++) {
      if (text.indexOf(STATUS_RULES[i][0]) >= 0) return { cls: STATUS_RULES[i][1], index: i + 1, needle: STATUS_RULES[i][0] };
    }
    return { cls: 'UNKNOWN', index: 0, needle: '' };
  }

  /** Returul e finalizat doar dacă pasul „Restituire sumă” are dată (pașii viitori fără dată nu contează). */
  function returnCompleted(scenario) {
    return !!scenario.steps && scenario.steps.some(function (step) { return step[1] && normalize(step[0]).indexOf(RETURN_STEP) >= 0; });
  }

  /** Starea finală a comenzii: pornește din status; un retur finalizat mută „păstrat” sau „anulat” în „returnat”. */
  function outcomeOf(scenario) {
    var verdict = classify(scenario.status);
    var start = START_STATE[verdict.cls];
    var done = returnCompleted(scenario);
    var outcome = (done && (start === 'kept' || start === 'cancelled')) ? 'returned' : start;
    return { outcome: outcome, verdict: verdict, completed: done, fromCancelled: done && start === 'cancelled' };
  }

  /**
   * Un număr scris în stil românesc: „1.000” = o mie (puncte de mii), „499,99” sau „499.99” = zecimale.
   * Nu depinde de limba browserului, spre deosebire de <input type="number">. Întoarce null dacă textul nu e un număr ≥ 0.
   */
  function parseLei(text) {
    var t = String(text).replace(/\s/g, '');
    if (t.indexOf(',') >= 0) t = t.replace(/\./g, '').replace(',', '.');
    else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, '');
    if (!/^\d+(\.\d+)?$/.test(t)) return null;
    var value = parseFloat(t);
    return isFinite(value) ? value : null;
  }

  /** Pragul din câmp: { bani, kind } cu kind = ok | invalid | capped; la text invalid se folosește pragul implicit. */
  function readThreshold() {
    var lei = parseLei(els.threshold.value);
    if (lei === null) return { bani: defaultThresholdBani(), kind: 'invalid' };
    if (lei > MAX_THRESHOLD_LEI) return { bani: MAX_THRESHOLD_LEI * 100, kind: 'capped' };
    return { bani: Math.round(lei * 100), kind: 'ok' };
  }

  /** Pragul implicit în BANI: cel din datele demo (generate cu pragul implicit al programului). */
  function defaultThresholdBani() {
    var data = root.EMAG_DEMO_DATA;
    return data && data.big && typeof data.big.threshold_bani === 'number' ? data.big.threshold_bani : FALLBACK_THRESHOLD_LEI * 100;
  }

  /** Totalurile lanțului pentru starea curentă: { bani, units } pe fiecare stare. */
  function totals() {
    var sums = {};
    CHAIN_ROWS.forEach(function (row) { sums[row[0]] = { bani: 0, units: 0 }; });
    var big = { count: 0 };
    var threshold = readThreshold();
    var limit = threshold.bani;
    ORDERS.forEach(function (order) {
      var result = outcomeOf(scenarioOf(order.id));
      var bani = order.unit * order.qty;
      if (result.outcome === 'paidonly') return;
      sums.ordered.bani += bani;
      sums.ordered.units += order.qty;
      sums[result.outcome].bani += bani;
      sums[result.outcome].units += order.qty;
      if (order.unit > limit) big.count += 1; // strict peste prag, ca în spend_analysis._big_items
    });
    return { sums: sums, big: big, limit: limit, threshold: threshold };
  }

  /** Scenariul ales pentru comanda `id`. */
  function scenarioOf(id) {
    var chosen = state[id];
    for (var i = 0; i < SCENARIOS.length; i++) if (SCENARIOS[i].id === chosen) return SCENARIOS[i];
    return SCENARIOS[0];
  }

  /** Eticheta de stare (culoare + text) pentru un rezultat. */
  function outcomeLabel(outcome) {
    var names = { kept: 'Păstrat', returned: 'Returnat', cancelled: 'Anulat', pending: 'În curs', unknown: 'Necunoscut' };
    return names[outcome] || outcome;
  }

  /**
   * Ce „citește” programul pentru o comandă, ca text (statusul blocului și, dacă există, pașii returului).
   * Programul mută câte o unitate PER APARIȚIE a numelui în retur: la o comandă cu mai multe bucăți, exemplul presupune
   * că returul listează produsul de tot atâtea ori (altfel ar trece în „returnat” doar unitățile listate).
   */
  function showsText(scenario, order) {
    var text = 'Status bloc: „' + scenario.status + '”' + (scenario.invented ? ' (text inventat pentru exemplu)' : '');
    if (scenario.steps) {
      text += ' · Retur: ' + scenario.steps.map(function (s) { return s[0] + (s[1] ? ' (cu dată)' : ' (fără dată)'); }).join(', ');
      if (order && order.qty > 1 && returnCompleted(scenario)) text += ' · Returul listează produsul de ' + order.qty + ' ori, câte o unitate pentru fiecare apariție a numelui';
    }
    return text;
  }

  /** Construiește cardurile comenzilor (o singură dată; apoi doar se actualizează rezultatele). */
  function buildOrders() {
    var h = Site.dom.h;
    els.cards = {};
    ORDERS.forEach(function (order) {
      var fieldset = h('fieldset', { class: 'sim-order__states' }, h('legend', { class: 'sr-only' }, 'Starea comenzii ' + order.id));
      SCENARIOS.forEach(function (scenario) {
        var input = h('input', { type: 'radio', name: 'stare-' + order.id, value: scenario.id });
        input.addEventListener('change', function () {
          state[order.id] = scenario.id;
          lastChanged = order.id;
          render();
        });
        fieldset.appendChild(h('label', { class: 'pill' }, input, h('span', null, scenario.label)));
      });
      var tag = h('span', { class: 'tag tag--big', hidden: true }, 'peste prag');
      var near = h('span', { class: 'tag tag--near', hidden: true }, 'egal cu pragul: nu intră');
      var shows = h('p', { class: 'sim-order__shows' });
      var result = h('p', { class: 'sim-order__result' });
      var card = h('article', { class: 'sim-order' },
        h('header', { class: 'sim-order__head' },
          h('p', { class: 'sim-order__id' }, 'Comanda ', h('b', null, order.id), ' · ', Site.dom.brandText(order.seller)),
          h('p', { class: 'sim-order__item' }, order.name, ' ', tag, near),
          h('p', { class: 'sim-order__price' }, Site.fmt.int(order.qty) + ' × ' + Site.fmt.lei(order.unit) + ' = ', h('b', null, Site.fmt.lei(order.unit * order.qty)))),
        fieldset, shows, result);
      els.cards[order.id] = { card: card, tag: tag, near: near, shows: shows, result: result, fieldset: fieldset };
      els.orders.appendChild(card);
    });
  }

  /** Actualizează cardurile: radio-urile, exemplul de text afișat, rezultatul și etichetele de prag. */
  function renderOrders(limit) {
    var h = Site.dom.h;
    ORDERS.forEach(function (order) {
      var ref = els.cards[order.id];
      var scenario = scenarioOf(order.id);
      var result = outcomeOf(scenario);
      Array.prototype.forEach.call(ref.fieldset.querySelectorAll('input'), function (input) { input.checked = input.value === scenario.id; });
      Site.dom.clear(ref.shows).appendChild(Site.dom.brandText('Exemplu de ce afișează eMAG: ' + showsText(scenario, order)));
      Site.dom.clear(ref.result).appendChild(h('span', null, h('span', { class: 'sim-order__arrow', 'aria-hidden': 'true' }, '→'), h('i', { class: 'sw sw--' + result.outcome, 'aria-hidden': 'true' }), h('b', null, outcomeLabel(result.outcome)),
        result.fromCancelled ? h('span', { class: 'sim-order__note' }, Site.dom.brandText('(marcat „anulat” de eMAG, dar returnat)')) : null));
      ref.tag.hidden = !(order.unit > limit);
      ref.near.hidden = order.unit !== limit;
      ref.card.setAttribute('data-outcome', result.outcome);
    });
  }

  /** Desenează lanțul (bonul) cu totalurile curente și bara proporțională. */
  function renderChain(data) {
    var h = Site.dom.h;
    var sums = data.sums;
    var rows = CHAIN_ROWS.filter(function (row) { return row[0] !== 'unknown' || sums.unknown.bani > 0; });
    var parts = sums.kept.bani + sums.returned.bani + sums.cancelled.bani + sums.pending.bani + sums.unknown.bani;
    var closes = parts === sums.ordered.bani;
    var list = h('div', { class: 'chain__rows' });
    rows.forEach(function (row) {
      var key = row[0];
      var isTotal = key === 'kept';
      list.appendChild(h('p', { class: 'chain__row' + (isTotal ? ' chain__row--total' : ''), 'data-state': key },
        h('span', { class: 'chain__label' }, key === 'ordered' ? null : h('i', { class: 'sw sw--' + key, 'aria-hidden': 'true' }), row[2] + row[1]),
        h('span', { class: 'chain__dots', 'aria-hidden': 'true' }),
        h('span', { class: 'chain__val' }, Site.fmt.lei(sums[key].bani))));
    });
    var bar = h('div', { class: 'chain__bar', 'aria-hidden': 'true' });
    ['kept', 'returned', 'cancelled', 'pending', 'unknown'].forEach(function (key) {
      if (sums[key].bani > 0) bar.appendChild(h('i', { class: 'ticket__seg ticket__seg--' + key, style: 'flex-grow:' + sums[key].bani }));
    });
    Site.dom.clear(els.chain).appendChild(h('div', null,
      h('h3', { class: 'chain__title', id: 'sim-chain-t' }, 'Lanțul comandat → plătit'),
      list,
      h('p', { class: 'chain__units' }, Site.fmt.units(sums.kept.units) + ' păstrate din ' + Site.fmt.units(sums.ordered.units) + ' comandate'),
      bar,
      h('p', { class: 'chain__check' + (closes ? '' : ' is-bad') }, closes
        ? 'Verificare: comandat = anulat + returnat + în curs' + (sums.unknown.bani > 0 ? ' + necunoscut' : '') + ' + plătit efectiv.'
        : 'Verificare eșuată: părțile nu se adună la total.'),
      h('p', { class: 'chain__big' }, 'Produse peste prag: ', h('b', null, Site.fmt.int(data.big.count)), ' (strict peste ' + Site.fmt.leiInt(data.limit) + ' pe bucată).'),
      h('p', { class: 'chain__units' }, 'Comenzile din exemplu nu au vouchere, transport sau taxe, deci suma plătită e chiar prețul lor.')));
    els.mini.textContent = '';
    els.mini.appendChild(h('span', { class: 'sim__mini-val' }, 'Plătit ' + Site.fmt.lei(sums.kept.bani)));
    var miniBar = h('span', { class: 'chain__bar chain__bar--mini' });
    ['kept', 'returned', 'cancelled', 'pending', 'unknown'].forEach(function (key) {
      if (sums[key].bani > 0) miniBar.appendChild(h('i', { class: 'ticket__seg ticket__seg--' + key, style: 'flex-grow:' + sums[key].bani }));
    });
    els.mini.appendChild(miniBar);
  }

  /** Panoul „Regula activă”: ce citește programul și ce hotărăște pentru comanda ultima schimbată. */
  function renderRule() {
    var h = Site.dom.h;
    var order = ORDERS.filter(function (o) { return o.id === lastChanged; })[0] || ORDERS[0];
    var scenario = scenarioOf(order.id);
    var result = outcomeOf(scenario);
    var key = order.id + '|' + scenario.id;
    if (key === ruleKey) return; // aceeași regulă: regiunea live n-are de ce să o repete (de ex. la schimbarea pragului)
    ruleKey = key;
    var info = EXPLAIN[scenario.id];
    var matched = result.verdict.index
      ? 'Regula ' + result.verdict.index + ' din ' + STATUS_RULES.length + ': textul de status conține „' + result.verdict.needle + '”.'
      : 'Niciuna dintre cele ' + STATUS_RULES.length + ' fraze cunoscute nu se potrivește.';
    var returnLine = scenario.steps
      ? (result.completed ? 'Returul are „Restituire sumă” cu dată: finalizat.' : 'Returul nu are „Restituire sumă” cu dată: nefinalizat.')
      : 'Nu există retur.';
    Site.dom.clear(els.rule).appendChild(h('div', null,
      h('h3', { class: 'rule__title', id: 'sim-rule-t' }, 'Regula activă'),
      h('p', { class: 'rule__who' }, 'Comanda ', h('b', null, order.id), ' · ', scenario.label, ' → ',
        h('i', { class: 'sw sw--' + result.outcome, 'aria-hidden': 'true' }), h('b', null, outcomeLabel(result.outcome))),
      h('p', { class: 'rule__text' }, Site.dom.brandText(info.rule)),
      h('dl', { class: 'rule__facts' },
        h('div', null, h('dt', null, 'Ce citește programul'), h('dd', null, showsText(scenario, order))),
        h('div', null, h('dt', null, 'Cum e citit'), h('dd', null, matched + ' ' + returnLine)),
        h('div', null, h('dt', null, 'Unde în cod'), h('dd', { translate: 'no' }, info.where)))));
  }

  /** Indiciul de sub câmp: ce prag a înțeles simulatorul (sau de ce folosește pragul implicit). Nu e regiune live. */
  function renderThresholdHint(threshold) {
    var text;
    if (threshold.kind === 'invalid') text = 'Nu e un număr valid; folosesc pragul implicit (' + Site.fmt.leiInt(threshold.bani) + ').';
    else if (threshold.kind === 'capped') text = 'Prea mare; folosesc maximul (' + Site.fmt.leiInt(threshold.bani) + ').';
    else text = 'Prag înțeles: ' + (threshold.bani % 100 === 0 ? Site.fmt.leiInt(threshold.bani) : Site.fmt.lei(threshold.bani)) + ' pe bucată.';
    els.hint.textContent = text;
    els.hint.classList.toggle('is-bad', threshold.kind !== 'ok');
    if (threshold.kind === 'ok') els.threshold.removeAttribute('aria-invalid');
    else els.threshold.setAttribute('aria-invalid', 'true');
  }

  /** Doar ce depinde de prag: etichetele „peste prag”, lanțul și indiciul. Regula activă nu se atinge. */
  function renderThreshold() {
    var data = totals();
    renderOrders(data.limit);
    renderChain(data);
    renderThresholdHint(data.threshold);
  }

  /** Redesenează tot: carduri, lanț, indiciu, regulă. */
  function render() {
    var data = totals();
    renderOrders(data.limit);
    renderChain(data);
    renderThresholdHint(data.threshold);
    renderRule();
  }

  /** La ieșirea din câmp: un text invalid sau prea mare se înlocuiește cu valoarea folosită, iar schimbarea se anunță o singură dată. */
  function onThresholdChange() {
    var threshold = readThreshold();
    if (threshold.kind === 'ok') return;
    var used = Site.fmt.leiInt(threshold.bani);
    els.threshold.value = String(Math.round(threshold.bani / 100));
    renderThreshold();
    Site.dom.announce(threshold.kind === 'invalid' ? 'Prag invalid: folosesc ' + used + '.' : 'Prag prea mare: folosesc ' + used + '.');
  }

  /** Revine la starea inițială și la pragul implicit. */
  function reset() {
    ORDERS.forEach(function (order) { state[order.id] = order.initial; });
    els.threshold.value = String(Math.round(defaultThresholdBani() / 100));
    lastChanged = ORDERS[0].id;
    ruleKey = '';
    render();
    Site.dom.announce('Simulatorul a revenit la exemplul inițial.');
  }

  /** Pornește simulatorul. */
  function init() {
    els.orders = doc.getElementById('sim-orders');
    els.chain = doc.getElementById('sim-chain');
    els.rule = doc.getElementById('sim-rule');
    els.mini = doc.getElementById('sim-mini');
    els.threshold = doc.getElementById('sim-threshold');
    els.hint = doc.getElementById('sim-threshold-hint');
    var resetButton = doc.getElementById('sim-reset');
    if (!els.orders || !els.chain || !els.rule || !els.mini || !els.threshold || !els.hint || !resetButton) return;
    buildOrders();
    els.threshold.addEventListener('input', renderThreshold); // la fiecare tastă: fără să rescrie regula din zona live
    els.threshold.addEventListener('change', onThresholdChange);
    resetButton.addEventListener('click', reset);
    ORDERS.forEach(function (order) { state[order.id] = order.initial; });
    els.threshold.value = String(Math.round(defaultThresholdBani() / 100));
    render();
  }

  Site.simulator = { init: init, classify: classify, statusRules: STATUS_RULES };
})(window);

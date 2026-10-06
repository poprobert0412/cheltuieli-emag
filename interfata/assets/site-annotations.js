/* site-annotations.js — raportul demo, montat cu componenta reală EmagDashboard și adnotat.
 * Primește: window.EmagDashboard, window.EMAG_DEMO_DATA și structura din #raport-demo (listă, fereastră, explicații).
 * Dă înapoi: nimic; montează raportul, desenează punctele numerotate peste blocurile [data-ed-block], evidențiază
 * blocul ales (chenar peste componentă, fără să-i modifice nodurile) și arată explicația într-un panou aria-live.
 * Starea e în adresă: #raport-demo/<adnotare>. Nu calculează cifre: exemplele din panou se citesc din datele demo.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  var STATE_TOKEN = 'raport-demo';
  var HOTSPOT_STEP_PX = 44; // distanța minimă pe verticală dintre două puncte numerotate
  var HOTSPOT_OFFSET_PX = 8; // cât sub marginea de sus a blocului stă punctul
  var MARK_PAD_PX = 6; // cât iese chenarul de evidențiere în afara blocului
  var SCROLL_MARGIN_PX = 14; // aer deasupra blocului după derulare în fereastră
  var REPORT_HEADING_LEVEL = 3; // secțiunea are h2: blocurile raportului sunt h3, cele din ele h4 (altfel ar apărea 12 h2 în plus)
  var NARROW_QUERY = '(max-width: 899.98px)'; // sub această lățime lista stă deasupra ferestrei și alegerea aduce fereastra sus

  /** Adnotările, în ordinea paginii raportului. `block` = valoarea data-ed-block din componentă. */
  var ITEMS = [
    { slug: 'cifra', block: 'hero', title: 'Cifra mare',
      shows: 'Banii plătiți efectiv pe ce ai păstrat: după vouchere și reduceri, cu transportul și taxele, minus banii primiți înapoi la retururi. Sub ea, din ce se compune: prețul de listă, reducerile, transportul și taxele.',
      source: '`paid.spent_bani` = „Total plătit” al comenzilor livrate sau ridicate − banii primiți înapoi la retururi. Perioada vine din `meta.first_order` și `meta.last_order`.',
      read: 'E „cât ai cheltuit”, pe baza sumelor plătite afișate de eMAG în fiecare comandă. Prețul de listă rămâne dedesubt, ca informație.',
      check: 'Că perioada acoperă toate comenzile tale și că, la o comandă pe care o știi, produsul și transportul se potrivesc cu „Total plătit” din pagina ei.' },
    { slug: 'lant', block: 'funnel', title: 'Lanțul comandat → plătit',
      shows: 'Cum se împarte suma comandată, după reduceri: plătit efectiv, returnat cu bani înapoi, anulat, în curs (și status necunoscut, dacă există), plus transportul și taxele comenzilor livrate. Culorile sunt fixe: plătit albastru, returnat portocaliu, anulat gri, în curs verde-smarald.',
      source: '`paid.funnel.*`: fiecare produs are o singură stare, iar comandat − anulat − returnat − în curs + transport și taxe = plătit efectiv. Dacă nu s-ar închide, ar apărea avertismentul „lanțul sumelor nu se închide”.',
      read: 'Segmentele sunt proporționale cu suma. Cu mouse-ul sau cu focusul vezi bucățile și procentul din total.',
      check: 'Că returnatul și anulatul sunt cele pe care le știi; un „în curs” mare cere o privire în cont.' },
    { slug: 'cifre', block: 'tiles', title: 'Cifre rapide',
      shows: 'Câte comenzi sunt păstrate integral, parțial, returnate sau anulate; cât ai primit înapoi la retururi și cât s-a anulat; câte produse păstrate depășesc pragul; totalul pe categoriile evidențiate.',
      source: '`orders.*`, `paid.funnel.returned_bani`, `paid.funnel.cancelled_bani`, `big.*` și `highlights.*`. O comandă e „păstrată parțial” dacă măcar un produs a rămas, iar altele au fost returnate sau anulate.',
      read: 'Fiecare cifră se citește singură; nu se adună între ele.',
      check: 'Că numărul de comenzi se potrivește cu istoricul din contul tău.' },
    { slug: 'categorii', block: 'categories', title: 'Pe ce s-au dus banii',
      shows: 'Banii plătiți pe categorii, ca bare, plus rândurile care nu sunt produse: „Transport și taxe” și, dacă există, retururile cu voucher sau diferențele la restituiri. „Vezi tabel” adaugă comandat, returnat, anulat și în curs pe fiecare categorie.',
      source: '`by_category` (`paid_kept_bani`) și `paid.extra_rows`. Fiecare produs primește partea lui din reducerile comenzii, proporțional cu prețul. Categoria vine din `config/categorii.json`: prima regulă care se potrivește cu numele produsului câștigă.',
      read: 'Toate rândurile se adună exact la cifra mare. Fiecare bară arată suma, procentul din total și bucățile păstrate.',
      check: 'Un „Necategorizat” mare înseamnă reguli lipsă: adaugă-le și refă raportul cu `--din-cache`.' },
    { slug: 'evidentiate', block: 'highlights', title: 'Categorii evidențiate',
      shows: 'Totalul plătit și lista produselor din categoriile cerute explicit, cu starea fiecărei părți (păstrat, returnat, anulat, în curs). Numele fiecărui produs duce la comanda lui pe eMAG.',
      source: '`highlights.<categorie>`: totalurile vin din `by_category`, iar lista e pe stări. Categoriile evidențiate se aleg din setările programului; lista afișată e limitată, iar toate rândurile sunt în `produse.csv`.',
      read: 'Cifra mare e ce ai plătit pe ce ai păstrat, după reduceri; sub ea sunt comandatul, returnatul, anulatul și, dacă există, ce e încă în curs.',
      check: 'Că produsele listate chiar sunt din categoria respectivă: regulile pe nume pot greși la denumiri ambigue.' },
    { slug: 'ani', block: 'years', title: 'Pe ani',
      shows: 'Banii plătiți efectiv pe anul în care s-a plasat comanda, pe coloane stivuite după cele mai mari categorii; restul se strâng la „Altele”.',
      source: '`paid.by_year_category` pentru grafic și `by_year` pentru tabel. Anul e cel al comenzii, nu al livrării sau al returului.',
      read: 'Un retur făcut în alt an scade din anul comenzii inițiale, nu din anul returului.',
      check: 'Că anii corespund cu momentele în care ai cumpărat; „Vezi tabel” arată și comandat, returnat și anulat pe an.' },
    { slug: 'mari', block: 'big', title: 'Achiziții peste prag',
      shows: 'Produsele al căror preț de listă pe bucată depășește strict pragul ({prag}, modificabil cu `--prag`), fiecare cu starea ei și suma plătită, după reduceri.',
      source: '`big.items`, filtrate după `big.threshold_bani`. „Marcat anulat de eMAG” înseamnă retur finalizat la un bloc pe care eMAG îl afișează „Livrare anulată”.',
      read: 'Butoanele de filtrare sunt „Toate” și starea fiecărei linii (păstrate, returnate, anulate, în curs, necunoscute), doar cele care există; totalul din subsolul tabelului urmează filtrul. Numele produsului și numărul comenzii duc la pagina comenzii pe eMAG (se deschid doar când apeși pe ele).',
      check: 'Că starea fiecărei achiziții mari e cea pe care o știi; un preț exact egal cu pragul nu apare aici.' },
    { slug: 'top', block: 'top', title: 'Produse cu cea mai mare valoare păstrată',
      shows: 'Produsele pe care ai plătit cel mai mult, după reduceri, grupate după nume. Ordinea e după suma totală, nu după prețul pe bucată.',
      source: '`top_products`: suma plătită din toate comenzile în care apare același nume (comparat fără diacritice și fără diferențe de litere), cu comanda cea mai recentă în `order_id`. Lista e limitată la primele.',
      read: 'Un produs cumpărat de mai multe ori apare o singură dată, cu bucățile și suma însumate. Numele duce la comanda lui cea mai recentă pe eMAG.',
      check: 'Că numele din listă sunt produse pe care le recunoști.' },
    { slug: 'preturi', block: 'preturi', title: 'Prețuri la același produs',
      shows: 'Produsele păstrate din cel puțin două comenzi diferite: prețul de listă pe bucată la fiecare cumpărare (primul, ultimul, minim, maxim), cu cât e mai scump sau mai ieftin ultimul preț față de cel dinainte, cât ai plătit peste cel mai mic preț și o micro-diagramă a evoluției.',
      source: '`price_history` (aceleași date sunt în `istoric_preturi.csv`). „Același produs” înseamnă același model: numele fără diacritice și cu litere mici, din care se scot culorile (`config/culori.json`); capacitatea și dimensiunea rămân în nume. Contează doar bucățile păstrate.',
      read: 'Cauți un produs după nume, ordonezi tabelul și deschizi istoricul unui produs cu săgeata din rândul lui: vezi numele din fiecare comandă, vânzătorul și linkul comenzii. Numele produsului duce la comanda cea mai recentă. În micro-diagramă, inelul e prețul minim, iar punctul plin e ultimul preț.',
      check: 'Prețul include promoții, e înainte de vouchere și poate veni de la vânzători diferiți: o diferență arată cum s-a schimbat prețul, nu dacă oferta a fost bună sau proastă. Dacă două produse diferite apar ca unul (sau unul ca două), verifică numele din istoric.' },
    { slug: 'vanzatori', block: 'sellers', title: 'Vânzători',
      shows: 'Banii plătiți pe produsele păstrate, pe vânzător: eMAG sau vânzători din marketplace (fără transport și taxe).',
      source: '`by_seller` (`paid_bani`): numele vânzătorului din titlul fiecărui bloc de comandă. Lista e limitată la primii.',
      read: 'Fiecare bară arată cât ai plătit acelui vânzător pe produse, procentul din total și bucățile.',
      check: 'Dacă vezi un vânzător necunoscut, caută-l în `produse.csv`, coloana „vanzator”.' },
    { slug: 'excluse', block: 'excluded', title: 'Rămase în afara calculului',
      shows: 'Blocuri plătite fără livrare de produse (de exemplu asigurări) și blocuri încă nelivrate.',
      source: '`paid_only` și `in_progress`, după statusul blocului. Nu intră în cât ai cheltuit.',
      read: 'Un „în curs” intră în calcul abia după ce statusul arată „Produse livrate” sau „Produse ridicate”.',
      check: 'Dacă ai comenzi vechi încă „în curs”, verifică-le în cont: poate nu mai vin.' },
    { slug: 'control', block: 'control', title: 'Cifre de control și avertismente',
      shows: 'Reconcilierea cifrei mari: „Total plătit” al blocurilor livrate, minus banii primiți înapoi, egal plătit efectiv; voucherele, transportul și taxele; starea retururilor; avertismentele, grupate pe cauze.',
      source: '`paid.reconciliation.*`, `reconciliation.*`, `warnings` și `warnings_detail`. Estimările (retururi finalizate fără sumă afișată) sunt numite ca atare. Titlurile și explicațiile grupelor vin din `config/avertismente.json`.',
      read: 'Un retur cu voucher sau sold eMAG nu se scade: voucherul scade deja „Total plătit” al comenzii în care îl folosești. Fiecare grupă de avertismente se deschide: ce înseamnă, dacă afectează totalurile, ce faci și comenzile concrete, cu link către eMAG.',
      check: 'Fiecare grupă cere o privire în cont, cu linkul comenzii la îndemână. Fără avertismente, verificările interne de sume au trecut; asta nu garantează că paginile eMAG au fost citite corect.' },
    { slug: 'metoda', block: 'method', title: 'Nota de metodă',
      shows: 'Regulile banilor plătiți, ale retururilor și ce nu intră în calcul, în câteva rânduri.',
      source: 'Textul fix al raportului; cifrele nu vin de aici.',
      read: 'Rezumă pe scurt ce explică secțiunea „Cum se calculează”, mai jos.',
      check: 'Citește-o o dată: explică de ce un retur cu voucher nu se scade și de ce un retur finalizat se numără ca returnat, nu ca anulare.' }
  ];

  var els = {};
  var current = ''; // slug-ul adnotării alese ('' = niciuna)
  var instance = null; // rezultatul EmagDashboard.mount (păstrat ca să se poată dezmonta)
  var expectedRaw = ''; // adresa pe care tocmai am scris-o noi: hashchange-ul ei nu mai derulează pagina
  var layoutQueued = false;

  /** Adnotarea cu slug-ul dat, sau null. */
  function findItem(slug) {
    for (var i = 0; i < ITEMS.length; i++) if (ITEMS[i].slug === slug) return ITEMS[i];
    return null;
  }

  /** Pragul de achiziție mare din datele demo, ca text; rezervă generică dacă lipsește. */
  function thresholdText() {
    var data = root.EMAG_DEMO_DATA;
    return data && data.big && typeof data.big.threshold_bani === 'number' ? Site.fmt.leiInt(data.big.threshold_bani) : 'pragul setat';
  }

  /** Înlocuiește {prag} în text. */
  function expand(text) {
    return String(text).replace('{prag}', thresholdText());
  }

  /** Propoziția „În demo: …” cu cifre din datele demo, sau null dacă datele nu permit. Nu aruncă niciodată. */
  function exampleLine(item) {
    var D = root.EMAG_DEMO_DATA;
    var f = Site.fmt;
    if (!D) return null;
    try {
      var P = D.paid, F = P.funnel;
      switch (item.slug) {
        case 'cifra':
          return f.lei(P.spent_bani) + ' plătit efectiv: la preț de listă ' + f.lei(P.list_kept_bani) + ', reduceri ' + f.lei(P.discounts_kept_bani) + ', transport și taxe ' + f.lei(P.fees_bani) + '; ' + f.units(P.spent_units) + ' păstrate din ' + f.int(D.orders.total) + ' comenzi.';
        case 'lant':
          var spent = F.ordered_bani - F.cancelled_bani - F.returned_bani - F.pending_bani - (F.unknown_bani || 0) + F.fees_bani;
          return 'comandat ' + f.lei(F.ordered_bani) + ' − anulat ' + f.lei(F.cancelled_bani) + ' − returnat ' + f.lei(F.returned_bani) + ' − în curs ' + f.lei(F.pending_bani) + ' + transport și taxe ' + f.lei(F.fees_bani) + (spent === F.spent_bani ? ' = ' : ' ≠ ') + f.lei(F.spent_bani) + ' plătit efectiv.';
        case 'cifre':
          var O = D.orders;
          return f.int(O.total) + ' comenzi: ' + f.int(O.kept_all) + ' păstrate integral, ' + f.int(O.kept_partial) + ' parțial, ' + f.int(O.returned_all) + ' returnate integral, ' + f.int(O.cancelled_all) + ' anulate integral, ' + f.int(O.in_progress) + ' în curs.';
        case 'categorii':
          var top = D.by_category[0];
          var withKept = D.by_category.filter(function (c) { return c.paid_kept_bani > 0; }).length;
          return f.int(withKept) + ' categorii cu produse păstrate; prima: ' + top.name + ', ' + f.lei(top.paid_kept_bani) + ' (' + f.pct(top.paid_kept_bani, P.spent_bani) + ' din cât ai cheltuit).';
        case 'evidentiate':
          return Object.keys(D.highlights).map(function (name) {
            var t = D.highlights[name].totals;
            return name + ': ' + f.units(t.kept_units) + ' păstrate, ' + f.lei(t.paid_kept_bani) + ' plătit';
          }).join('; ') + '.';
        case 'ani':
          var years = D.by_year;
          var best = years.reduce(function (a, b) { return b.spent_bani > a.spent_bani ? b : a; }, years[0]);
          return years.length + ' ani, de la ' + years[0].year + ' la ' + years[years.length - 1].year + '; cel mai mare: ' + best.year + ', ' + f.lei(best.spent_bani) + ' plătit.';
        case 'mari':
          var B = D.big;
          return f.int(B.items.length) + ' linii peste ' + f.leiInt(B.threshold_bani) + ' pe bucată: ' + f.units(B.kept_units) + ' păstrate, ' + f.units(B.returned_units) + ' returnate, ' + f.units(B.cancelled_units) + ' anulate.';
        case 'top':
          var p = D.top_products[0];
          return 'primul produs: ' + p.name + ', ' + f.lei(p.paid_bani) + ' plătit (' + f.units(p.units) + ').';
        case 'preturi':
          var S = D.price_history.summary;
          return f.int(S.products) + ' produse păstrate din cel puțin două comenzi; plătit peste cel mai mic preț: ' + f.lei(S.overpaid_vs_min_bani) + '; ultimul preț e mai mare la ' + f.int(S.last_vs_prev.pricier_products) + ' produse și mai mic la ' + f.int(S.last_vs_prev.cheaper_products) + '.';
        case 'vanzatori':
          var s = D.by_seller[0];
          return f.int(D.by_seller.length) + ' vânzători; primul: ' + s.seller + ', ' + f.lei(s.paid_bani) + '.';
        case 'excluse':
          return f.int(D.paid_only.length) + ' bloc(uri) plătite fără livrare și ' + f.int(D.in_progress.length) + ' încă în curs.';
        case 'control':
          var R = D.reconciliation, C = P.reconciliation;
          return 'total plătit ' + f.lei(C.paid_delivered_bani) + ' − primit înapoi ' + f.lei(C.cash_refunds_bani) + (C.credit_returns_added_bani ? ' + retururi cu voucher ' + f.lei(C.credit_returns_added_bani) : '') + ' = ' + f.lei(C.spent_bani) + '; ' + f.int(R.returns_total) + ' retururi, ' + f.int(R.returns_completed) + ' finalizate; ' + (D.warnings_detail ? f.int(D.warnings_detail.length) + ' grupe de avertismente.' : f.int(D.warnings.length) + ' avertismente.');
        default:
          return null;
      }
    } catch (e) {
      return null; // date demo incomplete: panoul rămâne fără exemplu, nu se strică
    }
  }

  /** Construiește lista laterală (câte un buton pe adnotare). */
  function buildRail() {
    var h = Site.dom.h;
    ITEMS.forEach(function (item, index) {
      var button = h('button', { class: 'rail__item', type: 'button', 'aria-pressed': 'false', 'data-slug': item.slug },
        h('span', { class: 'rail__no', 'aria-hidden': 'true' }, String(index + 1)),
        h('span', { class: 'rail__txt' }, item.title));
      button.addEventListener('click', function () { select(item.slug, { push: true, bring: true }); });
      els.rail.appendChild(h('li', null, button));
    });
  }

  /**
   * Construiește punctele numerotate din marginea ferestrei (poziționate de layout()). Sunt doar o afordanță pentru mouse
   * și deget: lista le dublează exact, deci stau în afara tastaturii (tabindex -1) și a cititoarelor de ecran (aria-hidden).
   */
  function buildHotspots() {
    var h = Site.dom.h;
    els.hotspots = ITEMS.map(function (item, index) {
      var button = h('button', {
        class: 'hs', type: 'button', 'aria-pressed': 'false', 'data-slug': item.slug, hidden: true,
        tabindex: '-1', 'aria-hidden': 'true',
        'aria-label': 'Adnotarea ' + (index + 1) + ': ' + item.title
      }, h('span', { class: 'hs__badge', 'aria-hidden': 'true' }, String(index + 1)));
      button.addEventListener('click', function () { select(item.slug, { push: true }); });
      els.overlay.appendChild(button);
      return button;
    });
    els.mark = h('div', { class: 'win__mark', hidden: true, 'aria-hidden': 'true' });
    els.overlay.appendChild(els.mark);
  }

  /** Construiește panoul de explicații o singură dată; apoi doar îi schimbă textele (focusul pe butoane nu se pierde). */
  function buildCaption() {
    var h = Site.dom.h;
    var facts = [['shows', 'Ce arată'], ['source', 'De unde vine'], ['read', 'Cum se citește'], ['check', 'Ce verifici']];
    els.count = h('span', { class: 'cap__count' });
    var prev = h('button', { class: 'btn btn--small', type: 'button' }, 'Anterioară');
    var next = h('button', { class: 'btn btn--small', type: 'button' }, 'Următoarea');
    var close = h('button', { class: 'btn btn--small btn--quiet', type: 'button' }, 'Închide explicația');
    prev.addEventListener('click', function () { step(-1); });
    next.addEventListener('click', function () { step(1); });
    close.addEventListener('click', function () { deselect({ push: true }); });
    els.capClose = close;
    els.capNav = h('div', { class: 'cap__nav' }, prev, next, close);

    els.capNo = h('span', { class: 'cap__no', 'aria-hidden': 'true' });
    els.capTitle = h('h3', { class: 'cap__title' });
    els.capIntro = h('p', { class: 'cap__intro' },
      'Alege o adnotare din listă sau apasă pe un punct numerotat din marginea ferestrei. Blocul ales se evidențiază în raport, iar aici vezi cum se citește. Cifrele din exemple sunt cele din datele demonstrative inventate.');
    els.capFacts = h('dl', { class: 'cap__facts' });
    els.factNodes = {};
    facts.forEach(function (pair) {
      var dd = h('dd');
      els.factNodes[pair[0]] = dd;
      els.capFacts.appendChild(h('div', null, h('dt', null, pair[1]), dd));
    });
    els.capExample = h('p', { class: 'cap__example' });
    els.capStart = h('button', { class: 'btn btn--small', type: 'button' }, 'Începe turul');
    els.capStart.addEventListener('click', function () { select(ITEMS[0].slug, { push: true, bring: true }); });

    var live = h('div', { class: 'cap__live', 'aria-live': 'polite', 'aria-atomic': 'true' },
      h('div', { class: 'cap__headline' }, els.capNo, els.capTitle), els.capIntro, els.capFacts, els.capExample);
    els.capBar = h('div', { class: 'cap__bar' }, els.count, els.capNav);
    Site.dom.clear(els.caption).appendChild(els.capBar);
    els.caption.appendChild(live);
    els.caption.appendChild(els.capStart);
  }

  /** Actualizează panoul pentru adnotarea curentă (sau starea de început, fără adnotare). */
  function renderCaption() {
    var item = findItem(current);
    var h = Site.dom.h;
    els.capBar.hidden = !item;
    els.capStart.hidden = !!item;
    els.capIntro.hidden = !!item;
    els.capFacts.hidden = !item;
    els.capNo.hidden = !item;
    if (!item) {
      els.count.textContent = '';
      els.capTitle.textContent = 'Alege o adnotare';
      els.capExample.hidden = true;
      return;
    }
    els.count.textContent = 'Adnotarea ' + (ITEMS.indexOf(item) + 1) + ' din ' + ITEMS.length;
    els.capNo.textContent = String(ITEMS.indexOf(item) + 1);
    els.capTitle.textContent = item.title;
    Object.keys(els.factNodes).forEach(function (key) {
      Site.dom.clear(els.factNodes[key]).appendChild(Site.dom.richText(expand(item[key])));
    });
    var example = exampleLine(item);
    els.capExample.hidden = !example;
    Site.dom.clear(els.capExample);
    if (example) els.capExample.appendChild(h('span', null, h('b', null, 'În demo: '), example));
  }

  /** Blocul din componentă pentru o adnotare, sau null dacă lipsește. */
  function blockOf(item) {
    return item && els.mount ? els.mount.querySelector('[data-ed-block="' + item.block + '"]') : null;
  }

  /** Poziționează punctele și chenarul de evidențiere după pozițiile actuale ale blocurilor. */
  function layout() {
    layoutQueued = false;
    if (!els.hotspots) return;
    var bodyRect = els.body.getBoundingClientRect();
    var placed = ITEMS.map(function (item, index) {
      var el = blockOf(item);
      if (!el) return { index: index, el: null };
      var rect = el.getBoundingClientRect();
      return { index: index, el: el, top: rect.top - bodyRect.top, left: rect.left - bodyRect.left, width: rect.width, height: rect.height };
    });
    var lastTop = -Infinity;
    placed.filter(function (p) { return p.el; }).sort(function (a, b) { return a.top - b.top || a.index - b.index; }).forEach(function (p) {
      p.spot = Math.max(p.top + HOTSPOT_OFFSET_PX, lastTop + HOTSPOT_STEP_PX); // fără suprapuneri între puncte
      lastTop = p.spot;
    });
    placed.forEach(function (p) {
      var button = els.hotspots[p.index];
      button.hidden = !p.el;
      if (p.el) button.style.top = Math.round(p.spot) + 'px';
    });
    var chosen = placed.filter(function (p) { return ITEMS[p.index].slug === current && p.el; })[0];
    els.mark.hidden = !chosen;
    if (chosen) {
      els.mark.style.top = Math.round(chosen.top - MARK_PAD_PX) + 'px';
      els.mark.style.left = Math.round(chosen.left - MARK_PAD_PX) + 'px';
      els.mark.style.width = Math.round(chosen.width + 2 * MARK_PAD_PX) + 'px';
      els.mark.style.height = Math.round(chosen.height + 2 * MARK_PAD_PX) + 'px';
    }
  }

  /** Cere o recalculare a pozițiilor, cel mult una pe cadru. */
  function queueLayout() {
    if (layoutQueued) return;
    layoutQueued = true;
    root.requestAnimationFrame(layout);
  }

  /** Derulează fereastra până când blocul adnotării e în partea de sus. */
  function scrollFrameTo(item) {
    var el = blockOf(item);
    if (!el) return;
    var top = el.getBoundingClientRect().top - els.scroll.getBoundingClientRect().top + els.scroll.scrollTop - SCROLL_MARGIN_PX;
    els.scroll.scrollTo({ top: Math.max(0, top), behavior: Site.dom.prefersReducedMotion() ? 'auto' : 'smooth' });
  }

  /** Marchează selecția în listă și în puncte (aria-pressed). */
  function markSelection() {
    var mark = function (button) { button.setAttribute('aria-pressed', String(button.getAttribute('data-slug') === current)); };
    Array.prototype.forEach.call(els.rail.querySelectorAll('button'), mark);
    (els.hotspots || []).forEach(mark);
  }

  /** True pe ecran îngust, unde lista stă deasupra ferestrei. */
  function isNarrow() {
    return !!(root.matchMedia && root.matchMedia(NARROW_QUERY).matches);
  }

  /**
   * Alege o adnotare. `push` scrie adresa (cu intrare în istoric); `page` derulează și pagina până la fereastră;
   * `bring` (alegere din listă) aduce fereastra sus pe ecran îngust, ca blocul evidențiat să se vadă de la început.
   */
  function select(slug, opts) {
    var item = findItem(slug);
    if (!item) return;
    opts = opts || {};
    var changed = current !== slug;
    current = slug;
    markSelection();
    renderCaption();
    layout();
    if (changed) scrollFrameTo(item);
    // fereastra + panoul trebuie să încapă împreună în ecran: la intrare din adresă o aducem sus, la clic doar cât e nevoie
    // La Anterioară/Următoarea pe ecran îngust pagina rămâne pe loc: butoanele sunt sub degetul omului și nu trebuie să fugă
    if (opts.page) els.win.scrollIntoView({ block: 'start' });
    else if (opts.bring) els.win.scrollIntoView({ block: isNarrow() ? 'start' : 'nearest' });
    else if (opts.push && !isNarrow()) els.win.scrollIntoView({ block: 'nearest' });
    if (opts.push) {
      expectedRaw = STATE_TOKEN + '/' + slug;
      Site.state.navigate(expectedRaw);
    }
  }

  /** Renunță la selecție; `push` readuce adresa la #raport-demo. */
  function deselect(opts) {
    opts = opts || {};
    current = '';
    markSelection();
    renderCaption();
    layout();
    if (opts.push) {
      expectedRaw = STATE_TOKEN;
      Site.state.navigate(expectedRaw);
    }
  }

  /** Trece la adnotarea următoare (delta = 1) sau anterioară (-1), circular. */
  function step(delta) {
    var index = ITEMS.indexOf(findItem(current));
    var next = (index + delta + ITEMS.length) % ITEMS.length;
    select(ITEMS[next].slug, { push: true });
  }

  /** Handler pentru adresă: #raport-demo și #raport-demo/<adnotare>; orice altă adresă cât timp e o selecție o anulează. */
  function onState(parsed, ctx) {
    if (parsed.token !== STATE_TOKEN) {
      expectedRaw = '';
      if (current) deselect(); // „Înapoi” până la o adresă fără adnotare: selecția și chenarul dispar odată cu ea
      return;
    }
    var internal = parsed.raw === expectedRaw;
    expectedRaw = '';
    var item = findItem(parsed.sub);
    if (parsed.sub && !item) { Site.state.replace(STATE_TOKEN); }
    var page = !internal && ctx.source !== 'popstate';
    if (item) select(item.slug, { page: page });
    else if (current) deselect();
  }

  /** Montează componenta cu datele demo; întoarce false (și arată un mesaj) dacă nu se poate. */
  function mountReport() {
    var h = Site.dom.h;
    var api = root.EmagDashboard;
    var data = root.EMAG_DEMO_DATA;
    var problem = !api ? 'Componenta raportului nu s-a încărcat (assets/dashboard.js lipsește).'
      : !data ? 'Datele demonstrative nu s-au încărcat (assets/demo-data.js lipsește).' : '';
    if (!problem) {
      try {
        instance = api.mount(els.mount, data, { demo: true, headingLevel: REPORT_HEADING_LEVEL });
        return true;
      } catch (error) {
        problem = 'Raportul demonstrativ n-a putut fi montat: ' + (error && error.message ? error.message : 'eroare necunoscută') + '.';
      }
    }
    Site.dom.clear(els.mount).appendChild(h('p', { class: 'viewer__empty' }, problem));
    return false;
  }

  /** Pornește secțiunea: construiește lista, punctele și panoul, montează raportul, urmărește schimbările de mărime. */
  function init() {
    els.section = doc.getElementById('raport-demo');
    els.win = doc.getElementById('demo-win');
    els.rail = doc.getElementById('demo-rail');
    els.scroll = doc.getElementById('demo-scroll');
    els.body = doc.getElementById('demo-body');
    els.overlay = doc.getElementById('demo-overlay');
    els.mount = doc.getElementById('demo-mount');
    els.caption = doc.getElementById('demo-caption');
    if (!els.section || !els.win || !els.rail || !els.scroll || !els.body || !els.overlay || !els.mount || !els.caption) return;

    buildRail();
    buildHotspots();
    buildCaption();
    var mounted = mountReport();
    renderCaption();
    if (mounted) {
      layout();
      if ('ResizeObserver' in root) {
        var observer = new root.ResizeObserver(queueLayout);
        observer.observe(els.mount);
        observer.observe(els.scroll);
      } else {
        root.addEventListener('resize', queueLayout);
      }
    }
    Site.state.register(function (parsed) { return parsed.token === STATE_TOKEN || current !== ''; }, onState);
  }

  /** Dezmontează raportul demo (scoate ascultătorii și nodurile componentei). */
  function unmount() {
    if (instance && typeof instance.unmount === 'function') instance.unmount();
    instance = null;
  }

  Site.annotations = { init: init, unmount: unmount, items: ITEMS };
})(window);

/* site-problems.js — căutarea din tabelul „Probleme și soluții”.
 * Primește: câmpul #problems-filter și tabelul #problems-table. Dă înapoi: nimic; ascunde rândurile care nu
 * conțin fragmentul căutat și anunță câte au rămas (aria-live), după o pauză, nu la fiecare tastă.
 * Compară fără diacritice, fără diferențe de litere și fără cifre, ghilimele sau paranteze: mesajele reale au
 * numere și nume în locul lui „…”, iar tabelul le ține locul.
 * Nu modifică textele rândurilor și nu scrie nimic în adresă.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  var COUNT_DELAY_MS = 500; // contorul se anunță după ce omul s-a oprit din scris; rândurile se filtrează imediat
  var timer = 0;

  /** Text de comparat: fără diacritice, litere mici, fără cifre, ghilimele, paranteze și „…”, spații unice. NFKD face din „…” trei puncte, deci și ele pleacă. */
  function normalize(text) {
    return String(text)
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/\.{3}|[0-9'"„”‘’“”()\[\]…]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  }

  /** Scrie contorul după pauză și doar dacă textul s-a schimbat (aceeași valoare nu se anunță a doua oară). */
  function showCount(counter, text) {
    root.clearTimeout(timer);
    if (!text) { counter.textContent = ''; return; }
    timer = root.setTimeout(function () {
      if (counter.textContent !== text) counter.textContent = text;
    }, COUNT_DELAY_MS);
  }

  /** Aplică filtrul: arată rândurile potrivite, ascunde grupurile rămase goale, actualizează numărătoarea. */
  function apply(input, table, counter) {
    var query = normalize(input.value);
    var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
    var matches = 0;
    var total = 0;
    var groupHeader = null;
    var groupHasMatch = false;
    var flushGroup = function () { if (groupHeader) groupHeader.hidden = !!query && !groupHasMatch; };
    rows.forEach(function (row) {
      if (row.classList.contains('empty')) return;
      if (row.classList.contains('group')) {
        flushGroup();
        groupHeader = row;
        groupHasMatch = false;
        return;
      }
      total += 1;
      var hit = !query || normalize(row.textContent).indexOf(query) >= 0;
      row.hidden = !hit;
      if (hit) { matches += 1; groupHasMatch = true; }
    });
    flushGroup();
    var empty = table.querySelector('tr.empty');
    if (empty) empty.hidden = !(query && matches === 0);
    showCount(counter, query ? (matches === 0 ? 'Niciun rezultat.' : matches + ' din ' + total + ' mesaje se potrivesc.') : '');
  }

  /** Leagă câmpul de căutare la tabel. */
  function init() {
    var input = doc.getElementById('problems-filter');
    var table = doc.getElementById('problems-table');
    var counter = doc.getElementById('problems-count');
    if (!input || !table || !counter) return;
    input.addEventListener('input', function () { apply(input, table, counter); });
  }

  Site.problems = { init: init };
})(window);

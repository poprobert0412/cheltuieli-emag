/* site-format.js — formatează sume, numere, date și dimensiuni în format românesc, cu Intl.*.
 * Primește: sume în BANI (int), numere, date ISO "AAAA-LL-ZZ", octeți. Dă înapoi: text.
 * Intl.NumberFormat('ro-RO') ascunde separatorul de mii la numerele de 4 cifre; de aceea se cere
 * useGrouping:'always' și se verifică rezultatul, cu rezervă manuală pentru motoare mai vechi.
 * Nu citește date din pagină și nu stă pe nimic altceva decât pe Intl.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var NBSP = ' ';
  var KB = 1024;
  var MB = KB * KB;

  /** Grupare manuală a miilor cu punct și zecimale cu virgulă (rezerva dacă Intl nu face ce trebuie). */
  function manualNumber(value, digits) {
    var parts = Math.abs(value).toFixed(digits).split('.');
    var whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (value < 0 ? '-' : '') + whole + (parts[1] ? ',' + parts[1] : '');
  }

  /** Funcție de formatare cu `digits` zecimale: Intl dacă dă exact formatul așteptat, altfel rezerva. */
  function numberFormatter(digits) {
    var intl = null;
    try {
      intl = new Intl.NumberFormat('ro-RO', { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: 'always' });
      var expected = digits ? '1.234,50' : '1.235';
      if (intl.format(1234.5) !== expected) intl = null;
    } catch (e) {
      intl = null;
    }
    return function (value) { return intl ? intl.format(value) : manualNumber(value, digits); };
  }

  var money = numberFormatter(2);
  var whole = numberFormatter(0);
  var oneDecimal = numberFormatter(1);

  /** Data ISO "AAAA-LL-ZZ" -> obiect Date la miezul nopții UTC, sau null dacă textul nu e o dată. */
  function parseIsoDate(iso) {
    var match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return match ? new Date(Date.UTC(+match[1], +match[2] - 1, +match[3])) : null;
  }

  var longDate = null;
  var shortDate = null;
  try {
    longDate = new Intl.DateTimeFormat('ro-RO', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
    shortDate = new Intl.DateTimeFormat('ro-RO', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' });
  } catch (e) { /* fără Intl.DateTimeFormat: se afișează data ISO așa cum e */ }

  Site.fmt = {
    NBSP: NBSP,
    /** 144927 -> "1.449,27 Lei" (cu spațiu nedespărțitor). */
    lei: function (bani) { return money(bani / 100) + NBSP + 'Lei'; },
    /** 144927 -> "1.449,27" (fără unitate, pentru coloane). */
    leiNumber: function (bani) { return money(bani / 100); },
    /** 144927 -> "1.449 Lei" (rotunjit la leu întreg). */
    leiInt: function (bani) { return whole(bani / 100) + NBSP + 'Lei'; },
    /** 1234 -> "1.234". */
    int: function (n) { return whole(n); },
    /** 12 -> "12 buc". */
    units: function (n) { return whole(n) + NBSP + 'buc'; },
    /** "2026-10-04" -> "4 octombrie 2026". */
    date: function (iso) { var d = parseIsoDate(iso); return d && longDate ? longDate.format(d) : String(iso || ''); },
    /** "2026-10-04" -> "04.10.2026". */
    dateShort: function (iso) { var d = parseIsoDate(iso); return d && shortDate ? shortDate.format(d) : String(iso || ''); },
    /** Octeți -> "123 KB" sau "1,5 MB". */
    bytes: function (n) {
      if (n >= MB) return (n % MB === 0 ? whole(n / MB) : oneDecimal(n / MB)) + NBSP + 'MB';
      if (n >= KB) return whole(n / KB) + NBSP + 'KB';
      return whole(n) + NBSP + 'B';
    },
    /** Procent din întreg, cu o zecimală: (1, 8) -> "12,5%". */
    pct: function (part, total) { return total > 0 ? oneDecimal(part / total * 100) + '%' : '0%'; }
  };
})(window);

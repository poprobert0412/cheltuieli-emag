/* app-format.js — formatarea numerelor, sumelor și datelor pentru ecran, în română.
 * Primește: numere (bani întregi, contoare) și date ca text. Dă înapoi: text gata de afișat; se expune ca window.App.format.
 * Folosește Intl când browserul are datele ro-RO; altfel formatare manuală cu același rezultat (fiecare formatator se
 * verifică o dată pe un exemplu cunoscut, ca un browser fără datele limbii să nu afișeze „1,234.50”).
 * Ce NU face: nu calculează nimic din raport (sumele vin gata făcute de aplicație, în bani).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const NBSP = '\u00a0';
  const DASH = '—';

  /** Grupează cu puncte cifrele unui întreg pozitiv scris ca text: „1234567” devine „1.234.567”. */
  function groupManually(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  /** Formatatorul de întregi: Intl dacă dă „1.234.567” pe exemplul de control, altfel cel manual. */
  function makeIntegerFormatter() {
    try {
      const formatter = new Intl.NumberFormat('ro-RO', { maximumFractionDigits: 0, useGrouping: 'always' });
      if (formatter.format(1234567) === '1.234.567') return function (n) { return formatter.format(n); };
    } catch (e) { /* browser fără useGrouping sau fără date ro-RO */ }
    return function (n) { return groupManually(String(Math.trunc(n))); };
  }
  const formatInteger = makeIntegerFormatter();

  /** Un număr întreg cu separator de mii („1.234”); „—” dacă valoarea nu e un număr. */
  function count(n) {
    return typeof n === 'number' && isFinite(n) ? formatInteger(Math.round(n)) : DASH;
  }

  /** O sumă din bani întregi, în Lei, cu două zecimale și spațiu nedespărțitor: 123456 devine „1.234,56 Lei”. */
  function lei(bani) {
    if (typeof bani !== 'number' || !isFinite(bani)) return DASH;
    const rounded = Math.round(bani);
    const abs = Math.abs(rounded);
    const cents = abs % 100;
    return (rounded < 0 ? '−' : '') + formatInteger(Math.floor(abs / 100)) + ',' + (cents < 10 ? '0' : '') + cents + NBSP + 'Lei';
  }

  /** O sumă în Lei dată ca număr (ex. pragul, 999.5): „999,50 Lei”, fără rotunjiri ciudate la zecimale. */
  function leiFromAmount(amount) {
    return lei(Math.round(amount * 100));
  }

  const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;

  /** „2026-10-05 11:07:55” devine „5 oct. 2026, 11:07”. Ora se ia așa cum e scrisă (fără conversie de fus). Textul necunoscut rămâne cum e. */
  function dateTime(text) {
    const match = DATE_PATTERN.exec(String(text === null || text === undefined ? '' : text));
    if (!match) return text === null || text === undefined || text === '' ? DASH : String(text);
    const hasTime = match[4] !== undefined;
    const date = new Date(Date.UTC(+match[1], +match[2] - 1, +match[3], hasTime ? +match[4] : 0, hasTime ? +match[5] : 0));
    const options = { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' };
    if (hasTime) { options.hour = '2-digit'; options.minute = '2-digit'; }
    try {
      return new Intl.DateTimeFormat('ro-RO', options).format(date);
    } catch (e) {
      return match[3] + '.' + match[2] + '.' + match[1] + (hasTime ? ' ' + match[4] + ':' + match[5] : '');
    }
  }

  /** Categoria de plural românească: 'one' (1), 'few' (0 și 2–19, ex. „comenzi”), 'other' (20 sau mai mult, ex. „de comenzi”). */
  function pluralCategory(n) {
    try {
      return new Intl.PluralRules('ro').select(n);
    } catch (e) {
      const last = n % 100;
      if (n === 1) return 'one';
      return n === 0 || (last > 0 && last < 20) ? 'few' : 'other';
    }
  }

  /** „325 de comenzi”: numărul formatat și forma de plural potrivită, din {one, few, other}. */
  function counted(n, forms) {
    return count(n) + ' ' + forms[pluralCategory(n)];
  }

  App.format = { count: count, lei: lei, leiFromAmount: leiFromAmount, dateTime: dateTime, counted: counted, pluralCategory: pluralCategory };
})(window);

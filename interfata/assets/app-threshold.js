/* app-threshold.js — câmpul „Prag pentru achiziții mari”: citire, validare, mesaje lângă câmp.
 * Primește: textul din câmpul #threshold. Dă înapoi, ca window.App.threshold: init(), read() -> {ok, value} sau {ok:false, message},
 * parse(text) (aceeași validare, fără DOM). `value` e null când câmpul e gol sau egal cu pragul implicit: atunci pagina nu trimite
 * nimic și aplicația folosește valoarea ei implicită (așa valoarea din pagină nu poate contrazice niciodată setările).
 * Regula: număr finit între 0 și plafon, ca la `--prag`; virgula sau punctul pentru zecimale (un om scrie „999,50”).
 * Ce NU face: nu pornește rularea (app-start.js) și nu hotărăște ce înseamnă „achiziție mare” (calculul e în aplicație).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  // Oglinzi ale settings.BIG_PURCHASE_THRESHOLD_LEI (500) și settings.MAX_BIG_PURCHASE_THRESHOLD_LEI (1 miliard) din
  // emag_spend/settings.py. Pagina le folosește doar ca să afișeze implicitul și să respingă din timp valori pe care --prag
  // le-ar respinge oricum; tests/test_app_ui_static.py compară cele două perechi de valori.
  const DEFAULT_THRESHOLD_LEI = 500;
  const MAX_THRESHOLD_LEI = 1000000000;
  // Cifre cu zecimale opționale. Mai strictă decât float() din Python doar la forme pe care nu le scrie un om (1e3, 1_000).
  const NUMBER_PATTERN = /^\d+(?:[.,]\d+)?$/;

  let field = null;
  let hint = null;

  /** Textul de ajutor de sub câmp, cu pragul implicit scris cu separator de mii. */
  function defaultHint() {
    return 'Produsele cu prețul pe bucată peste această sumă apar într-o listă separată în raport. Implicit: '
      + App.format.count(DEFAULT_THRESHOLD_LEI) + '\u00a0Lei.';
  }

  /** Validează textul din câmp: {ok:true, value:number|null} sau {ok:false, message}. */
  function parse(text) {
    const trimmed = String(text === null || text === undefined ? '' : text).trim();
    if (trimmed === '') return { ok: true, value: null };
    if (!NUMBER_PATTERN.test(trimmed)) return { ok: false, message: 'Scrie un număr, de exemplu 500 sau 999,50.' };
    const number = Number(trimmed.replace(',', '.'));
    if (!isFinite(number) || number < 0 || number > MAX_THRESHOLD_LEI) {
      return { ok: false, message: 'Alege un număr între 0 și ' + App.format.count(MAX_THRESHOLD_LEI) + '\u00a0Lei.' };
    }
    return { ok: true, value: number === DEFAULT_THRESHOLD_LEI ? null : number };
  }

  /** Arată sau scoate starea de eroare a câmpului (culoare, aria-invalid, mesaj în zona live de sub câmp). */
  function showMessage(message) {
    if (!field || !hint) return;
    if (message) {
      field.setAttribute('aria-invalid', 'true');
      hint.className = 'field__hint is-bad';
      hint.textContent = message;
    } else {
      field.removeAttribute('aria-invalid');
      hint.className = 'field__hint';
      hint.textContent = defaultHint();
    }
  }

  /** Citește câmpul. La valoare greșită arată mesajul lângă câmp, deschide opțiunile și mută focusul pe câmp. */
  function read() {
    const result = parse(field ? field.value : '');
    if (result.ok) {
      showMessage('');
      return result;
    }
    showMessage(result.message);
    const options = App.dom.byId('options');
    if (options) options.open = true;
    if (field) field.focus();
    return result;
  }

  /** Pune valoarea implicită în câmp și leagă verificările (la scriere se șterge eroarea, la ieșirea din câmp se verifică). */
  function init() {
    field = App.dom.byId('threshold');
    hint = App.dom.byId('threshold-hint');
    if (!field || !hint) return;
    field.value = String(DEFAULT_THRESHOLD_LEI);
    showMessage('');
    field.addEventListener('input', function () {
      if (field.getAttribute('aria-invalid') === 'true') showMessage('');
    });
    field.addEventListener('blur', function () {
      const result = parse(field.value);
      if (!result.ok) showMessage(result.message);
    });
  }

  App.threshold = { init: init, read: read, parse: parse };
})(window);

// Transformă o excepție a rulării într-un cod stabil și un mesaj în română, cu „ce s-a întâmplat” și „Ce faci”, pentru ecranul de eroare (portul lui emag_spend/app_errors.py).
// Primește: excepția ridicată de colectare, analiză sau salvare. Dă înapoi: { code, message }; codurile sunt stabile, ecranele și testele se bazează pe ele.
// Erorile proprii ale extensiei poartă un câmp `code` (constantele de aici), deci această unitate nu importă clasele lor: modulele care le aruncă importă codurile de aici, nu invers.
// Ce NU face: nu decide ce ecran se arată (asta e treaba ecranelor), nu scrie în jurnal și nu ridică excepții proprii.
import { LOGIN_WAIT_SECONDS } from '../settings.js';

export const CODE_LOGIN_TIMEOUT = 'login_timeout';
export const CODE_SESSION_EXPIRED = 'session_expired';
export const CODE_WORK_TAB_CLOSED = 'work_tab_closed';
export const CODE_PAGE_CHANGED = 'page_changed';
export const CODE_NETWORK = 'network';
export const CODE_BUSY = 'busy';
export const CODE_STORAGE_FULL = 'storage_full';
export const CODE_UNEXPECTED = 'unexpected';
export const ERROR_CODES = Object.freeze([
  CODE_LOGIN_TIMEOUT, CODE_SESSION_EXPIRED, CODE_WORK_TAB_CLOSED, CODE_PAGE_CHANGED, CODE_NETWORK, CODE_BUSY, CODE_STORAGE_FULL, CODE_UNEXPECTED,
]);

// Cât din mesajul unei excepții se arată omului: destul cât să fie util, prea puțin ca să umple ecranul (ca MAX_DETAIL_CHARS din app_errors.py).
const MAX_DETAIL_CHARS = 300;
// Tipurile de eroare ale limbajului (bug de program, nu mesaj scris pentru oameni): la ele se arată doar numele tipului, ca în Python la KeyError sau TypeError.
const PROGRAMMING_ERRORS = [TypeError, ReferenceError, SyntaxError, RangeError, EvalError, URIError];
// Fragmentul cu care Chrome anunță că spațiul chrome.storage s-a umplut (mesajul lui: „QUOTA_BYTES quota exceeded”).
const QUOTA_PATTERN = /quota/i;

/** Cât așteaptă extensia login-ul, în cuvinte (din settings.LOGIN_WAIT_SECONDS): „10 minute”. Îl folosesc și ecranele, ca textul din pagină să nu se despartă de valoarea din setări. */
export function loginWaitText() {
  return LOGIN_WAIT_SECONDS % 60 === 0 ? `${LOGIN_WAIT_SECONDS / 60} minute` : `${LOGIN_WAIT_SECONDS} de secunde`;
}

/** Prima linie a unui text, tăiată la MAX_DETAIL_CHARS (restul rămâne în jurnal). */
function firstLine(text) {
  const line = String(text ?? '').trim().split(/\r?\n/)[0];
  return line.length <= MAX_DETAIL_CHARS ? line : `${line.slice(0, MAX_DETAIL_CHARS).trimEnd()}…`;
}

/** Textul de arătat pentru o eroare neașteptată: mesajul ei dacă e scris pentru oameni, altfel doar tipul. */
function unexpectedDetail(error) {
  if (error instanceof Error) {
    if (PROGRAMMING_ERRORS.some((type) => error instanceof type)) return error.name;
    return firstLine(error.message) || error.name;
  }
  return typeof error;
}

/** „ (motiv)” dacă eroarea are un motiv scurt, altfel șir gol: se lipește după propoziția principală. */
function reasonSuffix(error) {
  const reason = typeof error?.reason === 'string' ? firstLine(error.reason) : '';
  return reason ? ` (${reason})` : '';
}

/** Codul și mesajul în română pentru `error`; nu ridică excepții și nu întoarce niciodată un mesaj gol. */
export function classifyError(error) {
  const known = typeof error?.code === 'string' && ERROR_CODES.includes(error.code) ? error.code : null;
  const code = known ?? (error instanceof Error && QUOTA_PATTERN.test(error.message) ? CODE_STORAGE_FULL : CODE_UNEXPECTED);
  switch (code) {
    case CODE_LOGIN_TIMEOUT:
      return { code, message: `Nu te-ai logat în cele ${loginWaitText()} alocate. Ce faci: apasă din nou «Pornește analiza» și loghează-te în fila eMAG care se deschide.` };
    case CODE_SESSION_EXPIRED:
      return { code, message: 'Sesiunea eMAG a expirat în timpul citirii. Ce faci: apasă din nou «Pornește analiza» și loghează-te când ți se cere.' };
    case CODE_WORK_TAB_CLOSED:
      return {
        code,
        message: 'Fila eMAG în care citea extensia a fost închisă sau mutată pe altă pagină înainte să se termine citirea. '
          + 'Ce faci: nu închide și nu folosi fila aceea până se termină analiza; apasă din nou «Pornește analiza».',
      };
    case CODE_PAGE_CHANGED:
      return {
        code,
        message: `O pagină din contul eMAG nu arată cum se așteaptă extensia${reasonSuffix(error)}; probabil eMAG și-a schimbat paginile. `
          + 'Ce faci: încearcă din nou; dacă se repetă, descarcă jurnalul și deschide un Issue în proiectul de pe GitHub, fără numere de comandă.',
      };
    case CODE_NETWORK:
      return {
        code,
        message: `Nu am putut citi o pagină din contul eMAG${reasonSuffix(error)}: conexiunea a căzut sau sesiunea s-a încheiat. `
          + 'Ce faci: verifică conexiunea la internet și că ești logat în eMAG; apoi apasă din nou «Pornește analiza».',
      };
    case CODE_BUSY:
      return {
        code,
        message: 'Rulează deja o analiză într-o altă filă a extensiei. '
          + 'Ce faci: treci în acea filă sau așteaptă să se termine; apoi apasă din nou «Pornește analiza».',
      };
    case CODE_STORAGE_FULL:
      return {
        code,
        message: 'Nu am avut loc să salvez analiza în spațiul extensiei din browser. '
          + 'Ce faci: apasă «Șterge datele» în raportul salvat (dacă ai unul) și pornește din nou analiza.',
      };
    default:
      return {
        code: CODE_UNEXPECTED,
        message: `A apărut o eroare neașteptată (${unexpectedDetail(error)}). `
          + 'Ce faci: încearcă din nou; dacă se repetă, descarcă jurnalul (poate conține numere de comandă: nu-l trimite nimănui fără să-l citești).',
      };
  }
}

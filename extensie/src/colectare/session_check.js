// Verifică dacă omul e logat în eMAG și, dacă nu, așteaptă să se logheze în fila de lucru (portul lui browser_session.ensure_logged_in).
// Primește: id-ul filei de lucru, raportorul de progres, un jurnal și un apel `onNeedLogin` (ecranul „Loghează-te în eMAG”). Dă înapoi: nimic; fila rămâne pe prima pagină a listei de comenzi, logat.
// Login-ul îl face OMUL, în fila eMAG: parola și codul 2FA nu trec prin extensie, care nu tastează în câmpuri și nu citește cookie-uri; extensia doar întreabă pagina dacă are „Comenzile mele” și „Log out”.
// Ce NU face: nu aduce fila în față singură (butonul de pe ecranul de login o face) și nu citește comenzi.
import { BASE_URL, LOGIN_POLL_SECONDS, LOGIN_WAIT_SECONDS, ORDER_LIST_FIRST_PAGE_PATH } from '../settings.js';
import { pageLoginState } from './page_functions.js';
import { NO_LOG, PHASE_WAITING_LOGIN, RunCancelled } from './progress.js';
import { CODE_LOGIN_TIMEOUT } from './run_errors.js';
import { NAVIGATION_TIMEOUT_MS, WorkTabClosed, tabIo } from './work_tab.js';

const MODULE = 'session_check';
const LOGIN_MARKER = 'login';

/** Omul nu s-a logat în timpul alocat (settings.LOGIN_WAIT_SECONDS); tip propriu, ca ecranul să-l recunoască fără să citească mesajul. */
export class LoginTimeout extends Error {
  /** Mesajul implicit merge în jurnal; omul vede mesajul din run_errors.js, făcut după codul erorii. */
  constructor(message = 'nu te-ai logat în timpul alocat; pornește din nou analiza') {
    super(message);
    this.name = 'LoginTimeout';
    this.code = CODE_LOGIN_TIMEOUT;
  }
}

/** True dacă adresa conține „login” (fără să conteze literele mari), ca verificarea din page_fetcher.py: pagina de login a eMAG. */
export function isLoginAddress(url) {
  return typeof url === 'string' && url.toLowerCase().includes(LOGIN_MARKER);
}

/** True dacă fila a ieșit din contul eMAG: adresa e goală (gazdă fără permisiune, de exemplu o pagină de login pe alt subdomeniu) sau e o adresă de login. */
export function isOutsideAccount(url) {
  return url === '' || url === undefined || url === null || isLoginAddress(url);
}

/** True dacă pagina din filă arată ca o pagină de cont. O pagină care nu poate fi citită (login pe altă gazdă, reîncărcare în curs) e „nelogat”; fila închisă se propagă. */
async function pageSaysLoggedIn(tabId, io) {
  try {
    const state = await io.runInTab(tabId, pageLoginState);
    return Boolean(state && state.logat);
  } catch (error) {
    if (error instanceof WorkTabClosed || error instanceof RunCancelled) throw error;
    return false;
  }
}

/**
 * Deschide istoricul de comenzi în fila de lucru și, dacă omul nu e logat, așteaptă să se logheze (cel mult LOGIN_WAIT_SECONDS, verificat la fiecare LOGIN_POLL_SECONDS).
 * Aruncă LoginTimeout după termen și RunCancelled dacă omul oprește rularea cât așteaptă (verificat la fiecare interogare).
 */
export async function ensureLoggedIn(tabId, progress, { onNeedLogin = () => {}, log = NO_LOG } = {}, io = tabIo) {
  progress.raiseIfCancelled();
  const url = BASE_URL + ORDER_LIST_FIRST_PAGE_PATH;
  const finalUrl = await io.navigate(tabId, url, NAVIGATION_TIMEOUT_MS);
  if (!isOutsideAccount(finalUrl) && await pageSaysLoggedIn(tabId, io)) {
    log.info(MODULE, 'sesiune eMAG activă, nu e nevoie de login');
    return;
  }
  const waitMinutes = Math.round(LOGIN_WAIT_SECONDS / 60);
  const message = `Loghează-te în fila eMAG (parola și codul 2FA le scrii tu). Aștept până la ${waitMinutes} minute.`;
  log.info(MODULE, message);
  progress.phase(PHASE_WAITING_LOGIN);
  progress.message(message);
  onNeedLogin();
  const deadline = io.now() + LOGIN_WAIT_SECONDS * 1000;
  while (io.now() < deadline) {
    await io.sleep(LOGIN_POLL_SECONDS * 1000);
    progress.raiseIfCancelled();
    if (await pageSaysLoggedIn(tabId, io)) {
      log.info(MODULE, 'login reușit');
      await io.navigate(tabId, url, NAVIGATION_TIMEOUT_MS);
      return;
    }
  }
  throw new LoginTimeout();
}

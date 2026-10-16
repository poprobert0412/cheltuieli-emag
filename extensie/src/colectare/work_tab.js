// Fila eMAG de lucru: o filă în fundal, creată goală (E6), navigată cu ascultătorul pus înainte, în care rulează funcțiile injectate (chrome.scripting).
// Primește: id-ul filei, adrese și funcții de injectat. Dă înapoi: adresa finală a navigării, rezultatul funcției injectate; erori tipizate (fila închisă, pagină inaccesibilă, navigare eșuată).
// Doar aici se vorbește cu chrome.tabs și chrome.scripting; scraperele primesc funcțiile de mai jos prin obiectul `tabIo` (și testele pun altul în loc, cu o filă falsă).
// Mesajele lui Chrome pe care se bazează traducerea erorilor au fost măsurate în Edge 155: „No tab with id: N” (cu sau fără punct), „Cannot access contents of the page...”,
// „Frame with ID 0 was removed.” (apare și când fila se închide, și când pagina se schimbă în timpul rulării; deosebirea o face existența filei).
// Ce NU face: nu știe de comenzi, retururi sau login (colectorul și scraperele) și nu citește cookie-uri.
import { CODE_WORK_TAB_CLOSED, CODE_NETWORK } from './run_errors.js';
import { now, sleep } from './waiting.js';

// Cât așteptăm ca o pagină să ajungă în starea „complete” (evenimentul load, cu imagini și scripturi). 60 de secunde: dublul lui FETCH_TIMEOUT_MS,
// fiindcă o filă din fundal se încarcă după cele din față și eMAG încarcă multe scripturi; depășirea înseamnă rețea căzută, nu o pagină lentă.
export const NAVIGATION_TIMEOUT_MS = 60_000;
// Cât așteptăm ca fila goală să se încarce: about:blank se termină instant, 10 secunde sunt doar o plasă de siguranță.
const OPEN_TIMEOUT_MS = 10_000;
const BLANK_URL = 'about:blank';
const STATUS_LOADING = 'loading';
const STATUS_COMPLETE = 'complete';
const NO_TAB_PATTERN = /No tab with id|The tab was closed/i;
const FRAME_REMOVED_PATTERN = /Frame with ID \d+ was removed/i;
const CANNOT_ACCESS_PATTERN = /Cannot access|Extension manifest must request permission|showing error page/i;

/** Fila de lucru nu mai există (omul a închis-o sau Chrome a descărcat-o). */
export class WorkTabClosed extends Error {
  /** `message` e textul lui Chrome (de ex. „No tab with id: 5”) sau mesajul implicit; omul vede mesajul din run_errors.js. */
  constructor(message = 'fila eMAG de lucru a fost închisă') {
    super(message);
    this.name = 'WorkTabClosed';
    this.code = CODE_WORK_TAB_CLOSED;
  }
}

/** Pagina din filă nu poate fi citită: gazdă fără permisiune (de exemplu pagina de login a eMAG), pagină de eroare a browserului sau pagină schimbată în timpul citirii. */
export class PageNotAccessible extends Error {
  /** `message` e textul lui Chrome sau un motiv scurt; rămâne și în `reason`, pentru ecranul de eroare. */
  constructor(message = 'pagina din fila de lucru nu poate fi citită') {
    super(message);
    this.name = 'PageNotAccessible';
    this.code = CODE_WORK_TAB_CLOSED;
    this.reason = message;
  }
}

/** Navigarea nu s-a încheiat în termen (rețea căzută sau pagină blocată). */
export class NavigationFailed extends Error {
  /** `reason`: de ce nu s-a încheiat navigarea (de ex. „pagina nu s-a încărcat în 60 de secunde”). */
  constructor(reason) {
    super(reason);
    this.name = 'NavigationFailed';
    this.code = CODE_NETWORK;
    this.reason = reason;
  }
}

/** Traduce o eroare de la chrome.tabs într-una a noastră: „No tab with id” înseamnă fila închisă; altele rămân cum sunt. */
function translateTabError(error) {
  const message = String(error?.message ?? error);
  return NO_TAB_PATTERN.test(message) ? new WorkTabClosed(message) : error;
}

/** True dacă fila `tabId` încă există. */
async function tabExists(tabId) {
  try {
    await chrome.tabs.get(tabId);
    return true;
  } catch {
    return false;
  }
}

/**
 * Așteaptă ca fila `tabId` să fie „complete” (fără să navigheze). Ascultătorul se pune înainte de verificare: o încărcare terminată între
 * `create` și ascultător nu se pierde, fiindcă starea se citește după ce ascultătorul există.
 */
function waitUntilComplete(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => finish(new NavigationFailed('fila de lucru nu s-a pornit')), timeoutMs);
    const onUpdated = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === STATUS_COMPLETE) finish(null);
    };
    const onRemoved = (id) => {
      if (id === tabId) finish(new WorkTabClosed());
    };
    function finish(error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      chrome.tabs.onRemoved.removeListener(onRemoved);
      if (error) reject(error);
      else resolve();
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.onRemoved.addListener(onRemoved);
    chrome.tabs.get(tabId).then((tab) => {
      if (tab.status === STATUS_COMPLETE) finish(null);
    }, (error) => finish(translateTabError(error)));
  });
}

/**
 * Deschide fila de lucru: goală (about:blank), inactivă și, dacă se dă `openerTabId`, lângă fila aplicației; întoarce id-ul ei.
 * Se creează goală, nu cu adresa eMAG, ca ascultătorul de încărcare să existe înaintea primei navigări (E6).
 */
export async function openWorkTab({ openerTabId } = {}) {
  const properties = { url: BLANK_URL, active: false };
  if (Number.isInteger(openerTabId)) properties.openerTabId = openerTabId; // null sau lipsă: nicio filă-mamă (Chrome refuză alte valori)
  const tab = await chrome.tabs.create(properties);
  await waitUntilComplete(tab.id, OPEN_TIMEOUT_MS);
  return tab.id;
}

/**
 * Navighează fila `tabId` la `url` și așteaptă să se încarce; întoarce adresa finală (după redirecturi) sau '' dacă fila a ajuns pe o gazdă fără permisiune.
 * Ascultătorul se pune ÎNAINTE de chrome.tabs.update (E6); „complete” se ia în seamă abia după un „loading” al acestei navigări, ca o încărcare veche să nu o încheie.
 */
export function navigate(tabId, url, timeoutMs = NAVIGATION_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let loadingSeen = false;
    const timer = setTimeout(() => finish(new NavigationFailed(`pagina nu s-a încărcat în ${Math.round(timeoutMs / 1000)} de secunde`)), timeoutMs);
    const onUpdated = (id, changeInfo, tab) => {
      if (id !== tabId) return;
      if (changeInfo.status === STATUS_LOADING) loadingSeen = true;
      else if (changeInfo.status === STATUS_COMPLETE && loadingSeen) finish(null, tab?.url ?? '');
    };
    const onRemoved = (id) => {
      if (id === tabId) finish(new WorkTabClosed());
    };
    function finish(error, finalUrl) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      chrome.tabs.onRemoved.removeListener(onRemoved);
      if (error) reject(error);
      else resolve(finalUrl);
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.onRemoved.addListener(onRemoved);
    try {
      chrome.tabs.update(tabId, { url }).catch((error) => finish(translateTabError(error)));
    } catch (error) {
      finish(translateTabError(error)); // argumente refuzate pe loc de Chrome: ascultătorii se scot, nu rămân agățați
    }
  });
}

/**
 * Rulează `func(...args)` în lumea izolată a paginii din fila `tabId` (E5) și întoarce rezultatul ei (null dacă n-a întors nimic).
 * Capcană: o funcție care aruncă în pagină NU respinge promisiunea, ci dă rezultat null (măsurat în Edge 155), deci funcțiile din page_functions.js nu aruncă niciodată.
 */
export async function runInTab(tabId, func, args = []) {
  let results;
  try {
    results = await chrome.scripting.executeScript({ target: { tabId }, func, args, world: 'ISOLATED' });
  } catch (error) {
    const message = String(error?.message ?? error);
    if (NO_TAB_PATTERN.test(message)) throw new WorkTabClosed(message);
    if (FRAME_REMOVED_PATTERN.test(message)) {
      if (await tabExists(tabId)) throw new PageNotAccessible('pagina s-a schimbat în timpul citirii');
      throw new WorkTabClosed(message);
    }
    if (CANNOT_ACCESS_PATTERN.test(message)) throw new PageNotAccessible(message);
    throw error;
  }
  const first = results?.[0];
  if (!first) throw new PageNotAccessible('fila nu a răspuns');
  return first.result;
}

/** Aduce fila `tabId` și fereastra ei în față (butonul „Deschide fila eMAG” de pe ecranul de login). */
export async function showTab(tabId) {
  let tab;
  try {
    tab = await chrome.tabs.update(tabId, { active: true });
  } catch (error) {
    throw translateTabError(error);
  }
  if (tab && tab.windowId !== undefined) await chrome.windows.update(tab.windowId, { focused: true });
}

/** Închide fila `tabId`; o filă care nu mai există nu e o problemă (omul sau Chrome au închis-o deja). */
export async function closeTab(tabId) {
  try {
    await chrome.tabs.remove(tabId);
  } catch {
    // Închisă deja: scopul (să nu rămână nicio filă de lucru) e atins.
  }
}

/** Ce primesc scraperele ca să vorbească cu fila; testele dau un obiect cu aceleași chei, cu o filă falsă și un ceas fals. */
export const tabIo = Object.freeze({ openWorkTab, navigate, runInTab, showTab, closeTab, sleep, now });

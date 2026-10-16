// Oglinda lui emag_spend/settings.py pentru extensie: aceleași nume și aceleași valori (setari.test.js le compară cu ce scrie Python).
// Conține adresele eMAG (căi relative la https://www.emag.ro), pragurile deciziilor de business și limitele colectării din pagini.
// Variabilele de mediu din Python (EMAG_FETCH_CONCURRENCY, EMAG_LOGIN_WAIT_SECONDS) nu există într-o extensie: aici au valoarea lor implicită.
// Ce NU face: nu are căi de foldere, browser, profil sau actualizări (nu au sens în extensie) și nu citește nimic din mediu.

export const BASE_URL = 'https://www.emag.ro';
export const ORDER_LIST_FIRST_PAGE_PATH = '/history/shopping?time=older';
export const ORDER_LIST_PAGE_PATH = '/history/shopping/{page}?time=older';
export const ORDER_DETAIL_PATH = '/history/shoppingdetails/{order_id}';
export const RETURN_LIST_PATH = '/user/return-history';

/** Calea paginii `page` din lista de comenzi (ORDER_LIST_PAGE_PATH.format(page=...)). */
export function orderListPagePath(page) {
  return ORDER_LIST_PAGE_PATH.split('{page}').join(String(page));
}

/** Calea paginii de detalii a comenzii `orderId` (ORDER_DETAIL_PATH.format(order_id=...)); numărul nu se validează aici (order_links.js o face). */
export function orderDetailPath(orderId) {
  return ORDER_DETAIL_PATH.split('{order_id}').join(String(orderId));
}

// Prag pentru „achiziție mare”: un produs cu preț STRICT mai mare de atât (în lei) este listat separat. 500 de lei e alegerea implicită a proiectului.
export const BIG_PURCHASE_THRESHOLD_LEI = 500;
// Plafonul pragului: 1 miliard de lei e peste orice achiziție reală, iar în bani (x100) rămâne mult sub cel mai mare întreg sigur din JavaScript (~9e15).
export const MAX_BIG_PURCHASE_THRESHOLD_LEI = 1_000_000_000;
// Categoriile evidențiate separat în raport (alcool și televizoare); numele trebuie să existe în config/categorii.json.
export const HIGHLIGHT_CATEGORIES = Object.freeze(['Alcool', 'Televizoare']);

// Câte pagini de detalii se cer simultan: 3 e prudent, cerem câteva sute de pagini din propriul cont și nu vrem să încărcăm serverul eMAG.
export const FETCH_CONCURRENCY = 3;
export const FETCH_RETRIES = 3;
export const FETCH_BACKOFF_SECONDS = 2.0;
export const FETCH_TIMEOUT_MS = 30_000;

// Cât așteptăm ca utilizatorul să se logheze în fila eMAG (parola și 2FA le scrie el, extensia nu le vede): 10 minute, verificat la fiecare 2 secunde.
export const LOGIN_WAIT_SECONDS = 600;
export const LOGIN_POLL_SECONDS = 2;

// Cât așteptăm ca o pagină de listă (randată de JavaScript) să-și încarce comenzile, înainte să o considerăm goală.
export const LIST_RENDER_TIMEOUT_SECONDS = 25;

// Plase de siguranță: opresc parcurgerea listelor dacă paginarea ar da erori.
export const MAX_LIST_PAGES = 500;
export const MAX_RETURN_LOAD_MORE_CLICKS = 200;

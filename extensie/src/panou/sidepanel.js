// Panoul consumă o autorizare unică de la clicul iconiței sau propriul buton de citire.
// Datele raportului și lista sunt reale și criptate; navigarea și ștergerea invalidează rezultatele întârziate.
import { loadLastAnalysis, LAST_ANALYSIS_KEY } from '../stocare/last_analysis.js';
import { createShoppingStore } from '../cumparaturi/shopping_store.js';
import { createShoppingInsights } from '../cumparaturi/shopping_insights.js';
import defaults from '../generat/shopping_config.js';
import { readActiveProduct } from './active_product.js';
import { compareProduct } from './product_comparison.js';
import { canonicalShoppingProductUrl as productUrl } from '../cumparaturi/shopping_schema.js';

const PANEL_REQUEST_KEY = 'panou_citire_produs';
const $ = (id) => document.getElementById(id);
const money = (bani) => `${new Intl.NumberFormat('ro-RO', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(bani / 100)} Lei`;
const store = createShoppingStore({ demo: false, defaults });
let product = null;
let revision = 0;
let disposed = false;
let lastRequest = null;
let dataInvalidated = false;

/** Ascunde imediat datele vechi și invalidează orice citire/calcul rămas în lucru. */
function clear(message) {
  revision += 1;
  product = null;
  $('product').hidden = true;
  $('panel-status').textContent = message;
  $('target-message').textContent = '';
  $('target-price').value = '';
}

/** O generație ștearsă nu este reautorizată: numai reload construiește un consumator nou. */
function dataDeleted() {
  dataInvalidated = true;
  clear('Datele au fost șterse. Reîncarcă panoul.');
  $('read-product').textContent = 'Reîncarcă panoul';
}

/** Afișează preț și zi fără HTML din pagina produsului sau din istoric. */
function showHistory(id, purchase) {
  const node = $(id);
  node.replaceChildren();
  node.append(document.createTextNode(purchase ? money(purchase.unit_bani) : 'Necunoscut'));
  if (purchase) {
    const date = document.createElement('small');
    date.textContent = purchase.date;
    node.append(date);
  }
}

/** Actualizează comparația din ultima analiză; răspunsurile care preced ștergerea/navigarea nu se afișează. */
async function refreshHistory() {
  const current = product;
  if (!current) return;
  const version = ++revision;
  $('match-label').hidden = true;
  showHistory('last-price', null);
  showHistory('minimum-price', null);
  $('difference').textContent = '';
  $('analysis-date').textContent = '';
  try {
    const entry = await loadLastAnalysis();
    if (version !== revision || disposed) return;
    if (!entry || entry.summary?.meta?.demo) {
      $('panel-status').textContent = 'Nu există o analiză salvată.';
      return;
    }
    if (!entry.orders.length && entry.summary?.meta?.orders !== 0) {
      $('panel-status').textContent = 'Analiza salvată nu conține detaliile cumpărăturilor.';
      $('analysis-date').textContent = `Analiză: ${entry.created_at}`;
      return;
    }
    const insights = await createShoppingInsights(entry);
    if (version !== revision || disposed) return;
    $('analysis-date').textContent = `Analiză: ${entry.created_at}`;
    const comparison = compareProduct(current, insights.purchases);
    if (comparison.status === 'no-history') {
      $('panel-status').textContent = 'Produsul nu apare cu aceeași denumire în cumpărăturile tale.';
      return;
    }
    $('panel-status').textContent = '';
    $('match-label').hidden = false;
    showHistory('last-price', comparison.last);
    showHistory('minimum-price', comparison.minimum);
    if (comparison.last && current.price_bani !== null) {
      const difference = current.price_bani - comparison.last.unit_bani;
      $('difference').textContent = difference === 0 ? 'Același preț ca la ultima cumpărare' : `Cu ${money(Math.abs(difference))} ${difference < 0 ? 'sub' : 'peste'} ultima cumpărare`;
    }
  } catch {
    if (version === revision) clear('Datele salvate nu au putut fi citite.');
  }
}

/** Citirea paginii se execută exclusiv după acțiunea utilizatorului, fără monitorizare automată. */
async function readProduct() {
  if (dataInvalidated) { location.reload(); return; }
  clear('Se citește produsul…');
  const version = revision;
  $('read-product').disabled = true;
  try {
    const result = await readActiveProduct();
    if (version !== revision || disposed) return;
    if (result.status !== 'ok') {
      const states = { ineligible: 'Deschide o pagină de produs pe www.emag.ro.', stale: 'Fila s-a schimbat. Citește produsul din nou.', ambiguous: 'Produsul principal nu poate fi identificat fără ambiguitate.' };
      clear(states[result.status] ?? 'Produsul nu a putut fi citit.');
      return;
    }
    product = result;
    $('product-name').textContent = result.name;
    $('current-price').textContent = result.price_bani === null ? 'Necunoscut' : money(result.price_bani);
    $('product').hidden = false;
    const saved = await store.read();
    if (version !== revision || disposed) return;
    const target = saved.wishlist.find((item) => item.url === result.url)?.target_bani;
    if (target !== null && target !== undefined) $('target-price').value = (target / 100).toFixed(2).replace('.', ',');
    await refreshHistory();
  } catch { if (version === revision) clear('Produsul sau datele salvate nu au putut fi citite.'); }
  finally { $('read-product').disabled = false; }
}

/** Validează suma în bani și recitește fila înainte de actualizarea atomică a listei criptate. */
async function saveTarget(event) {
  event.preventDefault();
  const current = product;
  const version = revision;
  const raw = $('target-price').value.trim();
  const parts = raw.replace(',', '.').split('.');
  const target = Number(parts[0]) * 100 + Number((parts[1] ?? '').padEnd(2, '0'));
  if (!/^\d+(?:[,.]\d{1,2})?$/.test(raw) || !Number.isSafeInteger(target) || target <= 0) {
    $('target-message').textContent = 'Introdu un preț mai mare decât zero, cu cel mult două zecimale.';
    $('target-price').setAttribute('aria-invalid', 'true');
    $('target-price').focus();
    return;
  }
  $('target-price').removeAttribute('aria-invalid');
  if (!current || !productUrl(current.url)) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (version !== revision || tab?.id !== current.tabId || tab.url !== current.tabUrl) {
      clear('Fila s-a schimbat. Citește produsul din nou.');
      return;
    }
    await store.update((state) => {
      const existing = state.wishlist.find((item) => item.url === current.url);
      const item = { id: current.url, name: current.name, url: current.url, price_bani: current.price_bani, target_bani: target, observed_at: new Date().toISOString(), selected: true };
      if (existing) Object.assign(existing, item, { id: existing.id });
      else state.wishlist.push(item);
    });
    if (version === revision) $('target-message').textContent = 'Ținta a fost salvată.';
  } catch { if (version === revision) $('target-message').textContent = 'Ținta nu a putut fi salvată.'; }
}

/** Consumă autorizarea transmisă de worker; o filă schimbată nu primește o citire nouă implicită. */
async function consumeRequest() {
  const request = (await chrome.storage.session.get(PANEL_REQUEST_KEY))[PANEL_REQUEST_KEY];
  if (!request || request.requestId === lastRequest) return;
  lastRequest = request.requestId;
  await chrome.storage.session.remove(PANEL_REQUEST_KEY);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === request.tabId && tab.url === request.url) await readProduct();
  else clear('Fila s-a schimbat. Citește produsul din nou.');
}

/** Evenimentele de navigare șterg datele vechi fără să citească automat pagina următoare. */
function onUpdated(tabId, change) {
  if ((product?.tabId === tabId || $('read-product').disabled) && (change.url || change.status === 'loading')) clear('Fila s-a schimbat. Citește produsul din nou.');
}
function onActivated() { clear('Fila s-a schimbat. Citește produsul din nou.'); }
function onRemoved(tabId) { if (product?.tabId === tabId) clear('Fila produsului a fost închisă.'); }
function onStorage(changes, area) {
  if (area === 'session' && changes[PANEL_REQUEST_KEY]?.newValue) consumeRequest().catch(() => clear('Produsul nu a putut fi citit.'));
  if (area === 'local' && Object.values(changes).some((change) => change.newValue === undefined)) dataDeleted();
  else if (area === 'local' && changes[LAST_ANALYSIS_KEY]) refreshHistory();
}

$('read-product').addEventListener('click', readProduct);
$('target-form').addEventListener('submit', saveTarget);
$('open-report').addEventListener('click', async () => {
  try { const result = await chrome.runtime.sendMessage({ type: 'panou-raport' }); if (!result?.ok) $('panel-status').textContent = 'Raportul nu a putut fi deschis.'; }
  catch { $('panel-status').textContent = 'Raportul nu a putut fi deschis.'; }
});
chrome.tabs.onUpdated.addListener(onUpdated);
chrome.tabs.onActivated.addListener(onActivated);
chrome.tabs.onRemoved.addListener(onRemoved);
chrome.storage.onChanged.addListener(onStorage);
const unsubscribe = store.subscribe((state, error) => {
  if (!state) { if (error) clear('Datele salvate nu au putut fi citite.'); else dataDeleted(); return; }
  if (!product) return;
  const target = state.wishlist.find((item) => item.url === product.url)?.target_bani;
  $('target-price').value = target === null || target === undefined ? '' : (target / 100).toFixed(2).replace('.', ',');
});
window.addEventListener('pagehide', () => {
  disposed = true;
  revision += 1;
  unsubscribe();
  store.dispose();
  chrome.tabs.onUpdated.removeListener(onUpdated);
  chrome.tabs.onActivated.removeListener(onActivated);
  chrome.tabs.onRemoved.removeListener(onRemoved);
  chrome.storage.onChanged.removeListener(onStorage);
}, { once: true });
consumeRequest().catch(() => clear('Produsul nu a putut fi citit.'));

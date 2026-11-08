import { canonicalShoppingProductUrl as productUrl } from '../cumparaturi/shopping_schema.js';
import { extractProductPage } from './product_page.js';

/** Citește numai fila activă eligibilă; recitește identitatea după injectare pentru a refuza navigarea concurentă. */
export async function readActiveProduct(api = chrome) {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  const expected = productUrl(tab?.url);
  if (!expected || !Number.isInteger(tab?.id)) return { status: 'ineligible' };
  const results = await api.scripting.executeScript({ target: { tabId: tab.id }, world: 'ISOLATED', func: extractProductPage });
  const current = await api.tabs.get(tab.id);
  const [active] = await api.tabs.query({ active: true, currentWindow: true });
  if (active?.id !== tab.id || current.url !== tab.url || productUrl(current.url) !== expected) return { status: 'stale' };
  const product = results.find((item) => item.frameId === 0)?.result;
  if (!product || (product.status === 'ok' && product.url !== expected)) return { status: 'stale' };
  return { ...product, tabId: tab.id, tabUrl: tab.url };
}

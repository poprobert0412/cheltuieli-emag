import assert from 'node:assert/strict';
import { test } from 'node:test';
import vm from 'node:vm';
import { extractProductPage } from '../../src/panou/product_page.js';
import { canonicalShoppingProductUrl as productUrl } from '../../src/cumparaturi/shopping_schema.js';

const URL_PRODUCT = 'https://www.emag.ro/veioza-test-rosie/pd/DEMO123/';
const NAME = 'Veioză exemplu 40 cm, roșie';
/** Fixture sintetic: selectori stricți și JSON-LD inventat, fără pagini ori comenzi reale. */
function fixture({ products = [], heading = NAME, canonical = URL_PRODUCT, meta = {} } = {}) {
  const nodes = {
    'h1': [{ textContent: heading }],
    'link[rel="canonical"]': canonical === null ? [] : [{ getAttribute: () => canonical }],
    'script[type="application/ld+json"]': products.map((value) => ({ textContent: JSON.stringify(value) })),
    'meta[property="og:title"]': meta.name ? [{ content: meta.name }] : [],
    'meta[property="product:price:amount"]': meta.price ? [{ content: meta.price }] : [],
    'meta[property="product:price:currency"]': meta.currency ? [{ content: meta.currency }] : [],
  };
  return { querySelectorAll: (selector) => { assert.ok(selector in nodes, selector); return nodes[selector]; }, querySelector: (selector) => nodes[selector][0] ?? null };
}
const offer = (price = '239.99') => ({ '@type': 'Offer', price, priceCurrency: 'RON', url: URL_PRODUCT, seller: { name: 'Magazin inventat' } });
const product = (overrides = {}) => ({ '@type': 'Product', name: NAME, url: URL_PRODUCT, offers: offer(), ...overrides });
const extract = (options) => extractProductPage(fixture(options), { href: URL_PRODUCT });

test('extractorul este autonom în lumea izolată și întoarce text + bani întregi', () => {
  const isolated = vm.runInNewContext(`(${extractProductPage.toString()})`, { URL });
  const result = JSON.parse(JSON.stringify(isolated(fixture({ products: [product()] }), { href: URL_PRODUCT })));
  assert.equal(result.price_bani, 23999);
  assert.equal(result.name, NAME);
  assert.equal(result.url, URL_PRODUCT.slice(0, -1));
});
test('nu alege prețul recomandărilor, varianta diferită sau alt URL cu același titlu', () => {
  const other = product({ name: 'Veioză exemplu 60 cm, roșie', offers: offer('12.00') });
  const wrongUrl = product({ url: 'https://www.emag.ro/altul/pd/OTHER/' });
  assert.equal(extract({ products: [other, wrongUrl] }).price_bani, null);
  assert.equal(extract({ products: [product(), other, wrongUrl] }).price_bani, 23999);
});
test('mai multe produse principale sau canonical diferit sunt ambigue', () => {
  assert.equal(extract({ products: [product(), product()] }).status, 'ambiguous');
  assert.equal(extract({ canonical: 'https://www.emag.ro/altul/pd/OTHER/' }).status, 'ambiguous');
});
test('mai mulți selleri, AggregateOffer, monedă diferită sau rată nu dau preț curent', () => {
  for (const offers of [[offer(), offer('99')], { '@type': 'AggregateOffer', lowPrice: '99', priceCurrency: 'RON' }, { ...offer(), priceCurrency: 'EUR' }, offer('20 lei/lună')]) {
    assert.equal(extract({ products: [product({ offers })] }).price_bani, null);
  }
});
test('fallback meta cere titlu integral și monedă RON; DOM generic de preț nu este citit', () => {
  assert.equal(extract({ meta: { name: NAME, price: '103.50', currency: 'RON' } }).price_bani, 10350);
  assert.equal(extract({ meta: { name: `${NAME} bonus`, price: '103.50', currency: 'RON' } }).price_bani, null);
  assert.equal(extract({}).price_bani, null);
});
test('URL-uri ostile și pagini de cont nu sunt produse eligibile', () => {
  const credentialsUrl = new URL(URL_PRODUCT);
  credentialsUrl.username = 'exemplu';
  for (const url of ['http://www.emag.ro/x/pd/A/', 'https://www.emag.ro.evil.invalid/x/pd/A/', credentialsUrl.href, 'https://www.emag.ro:444/x/pd/A/', 'https://www.emag.ro/history/shopping', 'javascript:alert(1)']) assert.equal(productUrl(url), null, url);
  assert.equal(productUrl(`${URL_PRODUCT}?ref=card#price`), URL_PRODUCT.slice(0, -1));
});

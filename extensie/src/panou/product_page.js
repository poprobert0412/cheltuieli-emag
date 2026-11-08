// Funcția trimisă cu chrome.scripting rulează în lumea izolată, fără importuri sau mesaje din pagină.
// Citește numai produsul principal; o ambiguitate produce preț necunoscut, niciodată o alegere arbitrară.
/** Extrage date text și bani din pagina curentă; document/location se pot injecta în testele sintetice. */
export function extractProductPage(doc = document, pageLocation = location) {
  // Limite tehnice pentru JSON-LD venit dintr-o pagină externă: evită parsarea/traversarea nelimitată.
  const MAX_JSON_CHARS = 1_000_000;
  const MAX_NODES = 10_000;
  const normalize = (value) => String(value ?? '').trim().replace(/\s+/g, ' ').toLocaleLowerCase('ro');
  const clean = (value) => String(value ?? '').trim().replace(/\s+/g, ' ');
  const canonical = (value) => {
    try {
      const url = new URL(value, pageLocation.href);
      if (url.protocol !== 'https:' || url.hostname !== 'www.emag.ro' || url.port || url.username || url.password || !/^\/[^/]+\/pd\/[a-zA-Z0-9]+\/?$/.test(url.pathname)) return null;
      return `${url.origin}${url.pathname.replace(/\/$/, '')}`;
    } catch { return null; }
  };
  const url = canonical(pageLocation.href);
  if (!url) return { status: 'ineligible' };
  const canonicalNode = doc.querySelector('link[rel="canonical"]');
  if (canonicalNode && canonical(canonicalNode.getAttribute('href')) !== url) return { status: 'ambiguous' };
  const headings = [...doc.querySelectorAll('h1')].map((node) => clean(node.textContent)).filter(Boolean);
  if (headings.length !== 1) return { status: 'ambiguous' };
  const name = headings[0];
  const products = [];
  let count = 0;
  const visit = (root) => {
    const pending = [root];
    while (pending.length && ++count <= MAX_NODES) {
      const value = pending.pop();
      if (!value || typeof value !== 'object') continue;
      if (!Array.isArray(value)) {
        const types = Array.isArray(value['@type']) ? value['@type'] : [value['@type']];
        if (types.includes('Product') && normalize(value.name) === normalize(name)) {
          const identity = value.url ?? value['@id'];
          if (!identity || canonical(identity) === url) products.push(value);
        }
      }
      for (const child of Object.values(value)) pending.push(child);
    }
  };
  for (const script of doc.querySelectorAll('script[type="application/ld+json"]')) {
    if (script.textContent.length > MAX_JSON_CHARS) return { status: 'ambiguous' };
    try { visit(JSON.parse(script.textContent)); } catch { /* JSON-LD invalid nu se interpretează ca HTML. */ }
  }
  if (count > MAX_NODES || products.length > 1) return { status: 'ambiguous' };
  const money = (value) => {
    const text = String(value ?? '').trim();
    if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null;
    const [whole, fraction = ''] = text.split('.');
    const bani = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
    return Number.isSafeInteger(bani) && bani > 0 ? bani : null;
  };
  let price_bani = null;
  let seller = null;
  if (products.length === 1) {
    const rawOffers = products[0].offers;
    const offers = Array.isArray(rawOffers) ? rawOffers : rawOffers ? [rawOffers] : [];
    // AggregateOffer/mai mulți vânzători nu spun care este oferta principală din pagină.
    if (offers.length === 1 && offers[0]['@type'] === 'Offer' && (!offers[0].url || canonical(offers[0].url) === url) && offers[0].priceCurrency === 'RON') {
      price_bani = money(offers[0].price);
      seller = clean(offers[0].seller?.name) || null;
    }
  } else {
    // Fallback numai metadate globale explicite de produs; nu căutăm cifre în carduri/rate/recomandări.
    const names = [...doc.querySelectorAll('meta[property="og:title"]')];
    const prices = [...doc.querySelectorAll('meta[property="product:price:amount"]')];
    const currencies = [...doc.querySelectorAll('meta[property="product:price:currency"]')];
    if (names.length === 1 && normalize(names[0].content) === normalize(name) && prices.length === 1 && currencies.length === 1 && currencies[0].content === 'RON') price_bani = money(prices[0].content);
  }
  return { status: 'ok', name, url, price_bani, seller };
}

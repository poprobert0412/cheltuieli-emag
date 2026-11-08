// Vederea retururilor care cer atenție; nu presupune termene sau restituiri.
import { orderUrl, returnUrl } from '../calcul/order_links.js';
import { el, heading } from './ui_dom.js';

const RETURN_KINDS = new Set(['pending_return_without_result', 'completed_return_without_refund']);

/** Revalidează calea salvată prin validatorul comun al retururilor. */
function safeReturnLink(item) {
  try {
    const url = new URL(item.return_url);
    if (url.origin !== 'https://www.emag.ro' || url.search || url.hash || url.username || url.password) return null;
    return returnUrl(item.return_id, url.pathname);
  } catch { return null; }
}

/** Montează avertismentele de retur din aceeași analiză ca raportul. */
export function mountReturnsView(root, { insights, entry, demo }) {
  const groups = (insights.summary.warnings_detail ?? []).filter((group) => RETURN_KINDS.has(group.kind));
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  heading(root, 'De urmărit', `Din ultima analiză${demo ? ' demonstrativă' : ''} · ${entry.created_at ?? insights.summary.meta.generated_at}`);
  root.append(el('span', 'shopping-pill', `${total} ${total === 1 ? 'situație' : 'situații'}`));
  if (!total) root.append(el('p', 'shopping-empty', 'Nu sunt retururi de urmărit în această analiză.'));
  for (const group of groups) {
    for (const item of group.items) {
      const raw = entry.returns?.find((ret) => ret.return_id === item.return_id);
      const card = el('article', group.kind === 'pending_return_without_result' ? 'shopping-return shopping-return--pending' : 'shopping-return');
      card.append(el('h4', '', raw?.product_names?.join('; ') || item.text));
      const row = el('div', 'shopping-row');
      row.append(el('span', 'shopping-pill', item.status || group.title));
      if (group.kind === 'completed_return_without_refund') row.append(el('strong', 'shopping-warning', 'Suma nu este afișată'));
      card.append(row);
      if (raw?.steps?.length) {
        const timeline = el('ol', 'shopping-timeline');
        for (const step of raw.steps) timeline.append(el('li', '', step));
        card.append(timeline);
      }
      card.append(el('p', 'shopping-sub', group.kind === 'pending_return_without_result' ? 'Restituirea nu apare încă în analiza curentă.' : 'Separat de retururile cu sumă confirmată.'));
      const href = demo ? null : safeReturnLink(item);
      if (href) { const link = el('a', 'shopping-button', 'Deschide returul'); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); }
      else if (!demo) for (const id of item.order_ids ?? []) { const url = orderUrl(id); if (url) { const link = el('a', 'shopping-button', 'Deschide comanda'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); } }
      root.append(card);
    }
  }
}

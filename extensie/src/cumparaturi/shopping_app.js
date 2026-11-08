// Navigația cumpărăturilor; coordonează vederile, stocarea și anularea montărilor.
import { createShoppingStore } from './shopping_store.js';
import { createShoppingInsights } from './shopping_insights.js';
import { mountCampaignView } from './campaign_view.js';
import { mountBudgetView } from './budget_view.js';
import { mountReturnsView } from './returns_view.js';
import { mountTagsView } from './tags_view.js';
import { mountRecapView } from './recap_view.js';
import { button, el } from './ui_dom.js';

const SECTIONS = [['report', 'Raport'], ['campaign', 'Black Friday'], ['budget', 'Buget'], ['returns', 'Retururi'], ['tags', 'Etichete'], ['recap', 'Bilanț']];
const VIEWS = { campaign: mountCampaignView, budget: mountBudgetView, returns: mountReturnsView, tags: mountTagsView, recap: mountRecapView };

/** Montează funcțiile pe o analiză; dispose împiedică rezultatele întârziate să atingă pagina. */
export async function mountShoppingApp(root, { entry, demo = false, defaults = {}, signal }) {
  const store = createShoppingStore({ demo, defaults });
  let disposed = false; let version = 0; let cleanup = () => {}; let section = 'report';
  const report = root.parentElement.querySelector('#report-root');
  const nav = el('nav', 'shopping-nav'); nav.setAttribute('aria-label', 'Cumpărăturile tale');
  const panel = el('section', 'shopping-panel'); panel.id = 'shopping-panel'; panel.hidden = true;
  const status = el('p', 'shopping-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const host = el('div', 'shopping-app'); host.append(nav, panel, status); root.replaceChildren(host);
  const buttons = new Map();
  let state; let insights; let unsubscribe = () => {};
  const selections = {};

  /** Comite o vedere numai dacă rămâne cea mai recentă cerere. */
  async function render() {
    if (disposed) return;
    const current = ++version; cleanup(); cleanup = () => {};
    for (const [key, node] of buttons) node.setAttribute('aria-pressed', String(key === section));
    panel.hidden = section === 'report'; if (report) report.hidden = section !== 'report';
    if (section === 'report' || disposed) return;
    const focusWasInside = panel.contains(document.activeElement);
    const focused = focusWasInside ? document.activeElement.dataset.focus : null;
    const next = el('div', 'shopping-view');
    const active = () => !disposed && version === current;
    panel.setAttribute('aria-busy', 'true');
    try {
      const result = await VIEWS[section](next, { state, store, insights, entry, demo, selections, active, refresh: render });
      if (!active()) { result?.dispose?.(); return; }
      const restoreFocus = focusWasInside && panel.contains(document.activeElement);
      cleanup = () => result?.dispose?.(); panel.replaceChildren(next); panel.removeAttribute('aria-busy');
      if (restoreFocus) {
        const target = [...panel.querySelectorAll('[data-focus]')].find((node) => node.dataset.focus === focused && node.getClientRects().length > 0);
        target?.focus();
        // Copiii unui details închis pot avea încă recturi, dar refuză focusul.
        if (!target || document.activeElement !== target) buttons.get(section).focus();
      }
    } catch (error) {
      if (active()) { panel.replaceChildren(el('p', 'shopping-error', error.message)); panel.removeAttribute('aria-busy'); }
    }
  }

  for (const [key, label] of SECTIONS) {
    const node = button(label, () => { if (!state || !insights) return; section = key; status.textContent = ''; void render(); }); node.disabled = true;
    node.dataset.section = key; node.setAttribute('aria-pressed', String(key === 'report')); buttons.set(key, node); nav.append(node);
  }
  signal?.addEventListener('abort', dispose, { once: true });
  if (signal?.aborted) dispose();
  try {
    [state, insights] = await Promise.all([store.read(), createShoppingInsights(entry)]);
    if (disposed) return { dispose };
    for (const node of buttons.values()) node.disabled = false;
    unsubscribe = store.subscribe((next, error) => {
      if (disposed) return;
      if (error) { status.textContent = error.message; status.classList.add('is-bad'); return; }
      if (next === null) { dispose(); return; }
      state = next; status.textContent = ''; void render();
    });
  } catch (error) { dispose(); throw error; }

  /** Eliberează abonamentele și readuce raportul existent. */
  function dispose() {
    if (disposed) return; disposed = true; version += 1; cleanup(); unsubscribe(); store.dispose(); signal?.removeEventListener('abort', dispose);
    if (root.contains(host) && report) report.hidden = false;
    host.remove();
  }
  return { dispose };
}

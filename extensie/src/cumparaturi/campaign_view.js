// Lista Black Friday și bilanțul perioadei: țintele se păstrează după eveniment.
import { isValidShoppingUrl, isShoppingDate, isShoppingTime, validateCampaign, canonicalShoppingProductUrl, SHOPPING_LIMITS } from './shopping_schema.js';
import { button, budgetProgress, el, field, heading, inputBani, metric, money, moneyInput, submitButton, submitForm } from './ui_dom.js';

/** Verifică o zi ISO calendaristică reală, inclusiv pentru bilanțul retrospectiv. */
function isoDay(value) {
  if (!isShoppingDate(value)) throw new Error('Alege o dată validă.');
  return value;
}

/** Citește o oră în format 24 h, independent de limba browserului. */
function timeValue(value) {
  if (!isShoppingTime(value)) throw new Error('Introdu ora în format HH:mm, de la 00:00 la 23:59.');
  return value;
}

/** Montează lista și configurarea ei, folosind alocările motorului pentru bilanț. */
export async function mountCampaignView(root, ctx) {
  const { state, store, insights, selections, active, refresh } = ctx;
  const top = el('div', 'shopping-black-rule'); top.append(el('span', 'shopping-bf-logo', 'BLACK FRIDAY')); heading(top, 'Lista mea, bugetul meu.'); root.append(top);
  const form = el('form', 'shopping-form shopping-campaign-settings');
  const startGroup = el('fieldset', 'shopping-campaign-boundary'); startGroup.append(el('legend', '', 'Din')); form.append(startGroup);
  const from = field(startGroup, { name: 'from', label: 'Data', type: 'date', value: state.campaign.from, validate: isoDay });
  const start = field(startGroup, { name: 'start-time', label: 'Ora', value: state.campaign.start_time ?? '', validate: timeValue, maxLength: 5, inputMode: 'text' });
  const endGroup = el('fieldset', 'shopping-campaign-boundary'); endGroup.append(el('legend', '', 'Până în')); form.append(endGroup);
  const to = field(endGroup, { name: 'to', label: 'Data', type: 'date', value: state.campaign.to, validate: isoDay });
  const end = field(endGroup, { name: 'end-time', label: 'Ora', value: state.campaign.end_time ?? '', maxLength: 5, inputMode: 'text', validate: (value) => {
    timeValue(value);
    if (isShoppingDate(from.input.value) && isShoppingDate(to.input.value) && isShoppingTime(start.input.value)) {
      validateCampaign({ ...state.campaign, from: from.input.value, to: to.input.value, start_time: start.input.value, end_time: value });
    }
    return value;
  } });
  for (const item of [start, end]) item.input.placeholder = 'HH:mm';
  for (const item of [from, to, start]) item.input.addEventListener('blur', () => { if (isShoppingTime(end.input.value)) end.check(); });
  const budget = field(form, { name: 'campaign-budget', label: 'Bugetul meu · Lei', value: moneyInput(state.campaign.budget_bani), validate: inputBani, inputMode: 'decimal' });
  const status = el('p', 'shopping-status'); status.setAttribute('role', 'status');
  submitButton(form);
  const timezone = el('p', 'shopping-sub shopping-campaign-timezone', 'Ora României. Sfârșitul ales nu intră în perioadă.'); timezone.id = 'shopping-campaign-timezone'; form.append(timezone);
  for (const item of [from, to, start, end]) item.input.setAttribute('aria-describedby', `${item.input.getAttribute('aria-describedby')} ${timezone.id}`);
  submitForm(form, { from, to, start, end, budget }, async (values) => store.update((draft) => { draft.campaign = { from: values.from, to: values.to, start_time: values.start, end_time: values.end, time_zone: state.campaign.time_zone, budget_bani: values.budget }; }), status, active); root.append(form, status);
  const selected = state.wishlist.filter((p) => p.selected);
  const known = selected.reduce((sum, p) => sum + (p.price_bani ?? 0), 0);
  const unknown = selected.filter((p) => p.price_bani === null).length;
  const budgetCard = el('div', 'shopping-list-budget');
  if (state.campaign.budget_bani !== null) budgetCard.append(budgetProgress(known, state.campaign.budget_bani));
  const values = el('div', 'shopping-row shopping-sub');
  values.append(el('span', '', `Selectat: ${money(known)}${unknown ? ` · ${unknown} fără preț` : ''}`), el('strong', '', state.campaign.budget_bani === null ? 'Fără buget' : `${known > state.campaign.budget_bani ? 'Peste buget:' : 'Rămân'} ${money(Math.abs(state.campaign.budget_bani - known))}`)); budgetCard.append(values); root.append(budgetCard);
  const list = el('ul', 'shopping-list');
  for (const product of state.wishlist) {
    const item = el('li', 'shopping-item');
    const checkLabel = el('label', 'shopping-check'); const check = el('input'); check.type = 'checkbox'; check.checked = product.selected; check.dataset.focus = `select-${product.id}`;
    check.setAttribute('aria-label', `Selectează ${product.name}`); checkLabel.append(check);
    check.addEventListener('change', () => { void store.update((draft) => { const found = draft.wishlist.find((p) => p.id === product.id); if (found) found.selected = check.checked; }).catch((err) => { if (active()) { status.textContent = err.message; check.checked = product.selected; } }); });
    const name = el('div', 'shopping-item-name');
    if (product.url && isValidShoppingUrl(product.url)) { const link = el('a', '', product.name); link.href = product.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; name.append(link); } else name.append(el('span', '', product.name));
    name.append(el('small', '', `Ținta mea: ${money(product.target_bani)}`));
    if (product.observed_at) name.append(el('small', '', `Preț observat: ${product.observed_at.slice(0, 10)}`));
    const price = el('div', 'shopping-item-price shopping-money', money(product.price_bani));
    if (product.price_bani !== null && product.target_bani !== null) price.append(el('small', '', product.price_bani <= product.target_bani ? 'în țintă' : 'peste țintă'));
    const actions = el('div', 'shopping-item-actions');
    const edit = button('Editează', () => { selections.editWishlist = product.id; void refresh(); }); edit.dataset.focus = `edit-${product.id}`;
    const remove = button('Șterge', () => { void store.update((draft) => { draft.wishlist = draft.wishlist.filter((p) => p.id !== product.id); }).catch((err) => { if (active()) status.textContent = err.message; }); });
    remove.setAttribute('aria-label', `Șterge ${product.name}`); actions.append(edit, remove); item.append(checkLabel, name, price, actions); list.append(item);
  }
  if (!state.wishlist.length) root.append(el('p', 'shopping-empty', 'Lista este goală.'));
  root.append(list);
  const editing = state.wishlist.find((p) => p.id === selections.editWishlist);
  const details = el('details', 'shopping-editor'); details.open = Boolean(editing || selections.addWishlist);
  const summary = el('summary', '', editing ? 'Editează produsul' : 'Adaugă un produs'); details.append(summary);
  const productForm = el('form', 'shopping-form shopping-product-form');
  const name = field(productForm, { name: 'product-name', label: 'Produs', value: editing?.name ?? '', maxLength: SHOPPING_LIMITS.name, validate: (v) => { if (!v.trim()) throw new Error('Introdu numele produsului.'); return v.trim(); } });
  const url = field(productForm, { name: 'product-url', label: 'Link eMAG', value: editing?.url ?? '', maxLength: SHOPPING_LIMITS.url, type: 'url', validate: (v) => { if (!v.trim()) return ''; const canonical = canonicalShoppingProductUrl(v.trim()); if (!canonical) throw new Error('Introdu un link HTTPS de pe eMAG.'); return canonical; } });
  const price = field(productForm, { name: 'product-price', label: 'Preț observat · Lei', value: moneyInput(editing?.price_bani), inputMode: 'decimal', validate: inputBani });
  const target = field(productForm, { name: 'product-target', label: 'Prețul-țintă · Lei', value: moneyInput(editing?.target_bani), inputMode: 'decimal', validate: inputBani });
  const productStatus = el('p', 'shopping-status'); productStatus.setAttribute('role', 'status'); submitButton(productForm, editing ? 'Salvează produsul' : 'Adaugă produsul');
  if (editing) productForm.append(button('Renunță', () => { delete selections.editWishlist; void refresh(); }));
  submitForm(productForm, { name, url, price, target }, async (v) => {
    await store.update((draft) => {
      const previous = editing ? draft.wishlist.find((p) => p.id === editing.id) : null;
      const product = { id: editing?.id ?? crypto.randomUUID(), name: v.name, url: v.url, price_bani: v.price, target_bani: v.target, observed_at: v.price === null ? null : previous?.price_bani === v.price ? previous.observed_at : new Date().toISOString(), selected: previous?.selected ?? true };
      if (previous) Object.assign(previous, product); else if (!editing) draft.wishlist.push(product);
    });
    delete selections.editWishlist; delete selections.addWishlist;
    await refresh();
  }, productStatus, active);
  details.append(productForm, productStatus); root.append(details);
  const result = await insights.campaign(state.campaign);
  if (!active()) return;
  const bounds = validateCampaign(state.campaign);
  const ended = bounds.end_ms !== null && Date.now() >= bounds.end_ms;
  const recap = el('section', 'shopping-campaign-recap'); heading(recap, ended ? 'Bilanțul perioadei' : 'În perioada aleasă');
  if (result.time_required) recap.append(el('p', 'shopping-warning', 'Alege ora de început și ora de sfârșit.'));
  else if (result.available === false) recap.append(el('p', 'shopping-sub', 'Detaliul acestei perioade nu este disponibil în analiza salvată.'));
  else {
    const grid = el('div', 'shopping-grid'); grid.append(metric('Comenzi înregistrate', result.meta.orders), metric('Plătit efectiv', money(result.paid.spent_bani)), metric('Comenzi încă pe drum', money(result.paid.reconciliation?.in_progress_bani))); recap.append(grid);
  }
  if (result.meta.missing_times > 0) recap.append(el('p', 'shopping-warning', `Comenzi fără oră sigură, neincluse: ${result.meta.missing_times}.`));
  if (result.meta.missing_dates > 0) recap.append(el('p', 'shopping-warning', `Comenzi fără dată, neincluse: ${result.meta.missing_dates}.`));
  root.append(recap);
}

// Etichetele personale se leagă de achiziții; categoria și totalurile rămân ale motorului.
import { SHOPPING_LIMITS } from './shopping_schema.js';
import { el, field, heading, metric, money, submitButton, submitForm } from './ui_dom.js';

const SUGGESTIONS = ['Pentru casă', 'Muncă', 'Cadouri'];

/** Montează filtrarea și editarea liberă a etichetelor per achiziție. */
export function mountTagsView(root, { state, store, insights, selections, active, refresh }) {
  heading(root, 'Pentru ce am cumpărat', 'Etichete personale, peste categoriile existente');
  const tags = [...new Set([...SUGGESTIONS, ...Object.values(state.tags)])].sort((a, b) => a.localeCompare(b, 'ro'));
  const filterLabel = el('label', 'shopping-inline shopping-filter', 'Eticheta'); const select = el('select'); select.dataset.focus = 'tag-filter';
  for (const [value, text] of [['', 'Toate'], ['untagged', 'Fără etichetă'], ...tags.map((t) => [`tag:${t}`, t])]) { const option = el('option', '', text); option.value = value; select.append(option); }
  select.value = selections.tagFilter ?? ''; select.addEventListener('change', () => { selections.tagFilter = select.value; void refresh(); }); filterLabel.append(select); root.append(filterLabel);
  const datalist = el('datalist'); datalist.id = 'shopping-tag-suggestions'; for (const tag of tags) { const option = el('option'); option.value = tag; datalist.append(option); } root.append(datalist);
  const filtered = insights.purchases.filter((p) => !selections.tagFilter || (selections.tagFilter === 'untagged' ? !state.tags[p.id] : state.tags[p.id] === selections.tagFilter.slice(4)));
  const list = el('ul', 'shopping-list');
  for (const [index, purchase] of filtered.entries()) {
    const row = el('li', 'shopping-item shopping-tag-item');
    const product = el('div', 'shopping-item-name', purchase.name); product.append(el('small', '', purchase.category), el('small', '', `${purchase.date ?? 'Dată necunoscută'} · ${money(purchase.paid_bani)}`));
    const form = el('form', 'shopping-tag-form');
    const tag = field(form, { name: `tag-${index}`, label: `Eticheta pentru ${purchase.name}`, value: state.tags[purchase.id] ?? '', maxLength: SHOPPING_LIMITS.tag, validate: (v) => v.trim() });
    tag.input.setAttribute('list', datalist.id); tag.input.dataset.focus = `tag-${purchase.id}`; tag.input.closest('.shopping-field').classList.add('shopping-field--compact');
    const status = el('p', 'shopping-status'); status.setAttribute('role', 'status');
    submitButton(form); submitForm(form, { tag }, ({ tag: value }) => store.update((draft) => { if (value) draft.tags[purchase.id] = value; else delete draft.tags[purchase.id]; }), status, active);
    row.append(product, form, status); list.append(row);
  }
  if (!filtered.length) root.append(el('p', 'shopping-empty', insights.purchases.length ? 'Nicio achiziție cu această etichetă.' : 'Achizițiile nu sunt disponibile în această analiză.'));
  root.append(list);
  const total = metric('Totalul raportului', money(insights.summary.paid.spent_bani)); total.append(el('p', 'shopping-sub', 'Etichetele schimbă organizarea, nu sumele.')); root.append(total);
}

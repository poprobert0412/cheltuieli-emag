// Buget lunar/anual peste sumele motorului existent, fără recalcularea retururilor.
import { el, field, heading, inputBani, metric, money, moneyInput, submitButton, submitForm, budgetProgress, yearSelect } from './ui_dom.js';

/** Montează bugetul perioadei alese; comenzile în curs rămân separate. */
export async function mountBudgetView(root, ctx) {
  const { state, store, insights, selections, active, refresh } = ctx;
  heading(root, 'Bugetul meu');
  const currentYear = new Intl.DateTimeFormat('ro-RO', { year: 'numeric', timeZone: 'Europe/Bucharest' }).format(new Date());
  // Poți bugeta înainte de prima comandă; anii salvați rămân accesibili fără achiziții.
  const years = [...new Set([...insights.years.map(String), currentYear, ...Object.keys(state.budgets).map((key) => key.slice(0, 4))])].sort().reverse();
  const year = selections.budgetYear ?? years[0];
  const month = selections.budgetMonth ?? '';
  const controls = el('div', 'shopping-row shopping-period');
  controls.append(yearSelect(years, year, (value) => { selections.budgetYear = value; void refresh(); }));
  const label = el('label', 'shopping-inline', 'Perioada'); const select = el('select'); select.dataset.focus = 'month';
  const all = el('option', '', 'Tot anul'); all.value = ''; select.append(all);
  for (let n = 1; n <= 12; n += 1) {
    const value = String(n).padStart(2, '0'); const option = el('option', '', new Intl.DateTimeFormat('ro-RO', { month: 'long', timeZone: 'UTC' }).format(new Date(`${year}-${value}-15T12:00:00Z`)));
    option.value = value; select.append(option);
  }
  select.value = month; select.addEventListener('change', () => { selections.budgetMonth = select.value; void refresh(); }); label.append(select); controls.append(label); root.append(controls);
  const key = month ? `${year}-${month}` : year;
  const form = el('form', 'shopping-form shopping-form--inline');
  const amount = field(form, { name: 'budget', label: month ? 'Buget lunar · Lei' : 'Buget anual · Lei', value: moneyInput(state.budgets[key]), validate: inputBani, inputMode: 'decimal' });
  const status = el('p', 'shopping-status'); status.setAttribute('role', 'status');
  submitButton(form); submitForm(form, { amount }, async ({ amount: value }) => store.update((draft) => { if (value === null) delete draft.budgets[key]; else draft.budgets[key] = value; }), status, active);
  root.append(form, status);
  const lastDay = month ? new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate() : 31;
  const result = await insights.period(`${year}-${month || '01'}-01`, `${year}-${month || '12'}-${lastDay}`);
  if (!active()) return;
  if (result.available === false) { root.append(el('p', 'shopping-sub', 'Detaliul acestei perioade nu este disponibil în analiza salvată.')); return; }
  const spent = result.paid.spent_bani;
  const pending = result.paid.reconciliation?.in_progress_bani ?? null;
  const budget = state.budgets[key] ?? null;
  const main = metric('Rămas din buget', budget === null ? '—' : money(budget - spent), true);
  if (budget !== null) main.append(budgetProgress(spent, budget));
  main.append(el('p', 'shopping-sub', `${money(spent)} plătit efectiv${budget === null ? '' : ` din ${money(budget)}`}`)); root.append(main);
  const extras = el('div', 'shopping-grid');
  const onWay = metric('Comenzi încă pe drum', money(pending)); onWay.append(el('p', 'shopping-sub', 'Separat de plătit efectiv'));
  const potential = metric('Dacă păstrezi tot ce vine', budget === null || pending === null ? '—' : money(budget - spent - pending));
  if (budget !== null && pending !== null) potential.append(el('p', 'shopping-sub', budget < spent + pending ? 'Peste bugetul ales' : 'Ar rămâne disponibil'));
  extras.append(onWay, potential); root.append(extras);
}

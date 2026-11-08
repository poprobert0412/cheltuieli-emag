// Elemente și formulare pentru cumpărături; datele intră numai ca text.
import { formatLei, parseRefundAmount } from '../calcul/money_ro.js';

/** Creează un element fără interpretarea textelor ca HTML. */
export function el(tag, className = '', text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = String(text);
  return node;
}

/** Creează un buton al vederii. */
export function button(text, action, primary = false) {
  const node = el('button', `shopping-button${primary ? ' shopping-button--primary' : ''}`, text);
  node.type = 'button';
  if (action) node.addEventListener('click', action);
  return node;
}

/** Formatează bani întregi; absența nu este zero. */
export function money(value) { return value === null || value === undefined ? '—' : formatLei(value); }

/** Citește o sumă pozitivă sau nulă; gol înseamnă null. */
export function inputBani(value) {
  const text = value.trim();
  if (!text) return null;
  const parsed = parseRefundAmount(text);
  if (parsed === null || parsed < 0 || !Number.isSafeInteger(parsed)) throw new Error('Introdu o sumă validă, de cel puțin 0 Lei.');
  return parsed;
}

/** Valoare pentru editare, fără separator de mii. */
export function moneyInput(value) { return value === null || value === undefined ? '' : (value / 100).toFixed(2).replace('.', ','); }

/** Adaugă un câmp etichetat și eroarea sa, inclusiv verificare la blur. */
export function field(form, { name, label, value = '', type = 'text', validate = (v) => v, maxLength, inputMode }) {
  const wrap = el('div', 'shopping-field');
  const caption = el('label', '', label);
  const input = el('input');
  input.type = type; input.name = name; input.value = value;
  input.id = `shopping-${name}`; input.dataset.focus = name;
  if (maxLength) input.maxLength = maxLength;
  if (inputMode) input.inputMode = inputMode;
  caption.htmlFor = input.id;
  const error = el('span', 'shopping-field-error'); error.id = `${input.id}-error`;
  error.setAttribute('aria-live', 'polite'); input.setAttribute('aria-describedby', error.id);
  let touched = false;
  const check = () => {
    try { const result = validate(input.value); input.removeAttribute('aria-invalid'); error.textContent = ''; return { valid: true, value: result }; }
    catch (err) { input.setAttribute('aria-invalid', 'true'); error.textContent = err.message; return { valid: false }; }
  };
  input.addEventListener('blur', () => { touched = true; check(); });
  input.addEventListener('input', () => { if (touched) check(); });
  wrap.append(caption, input, error); form.append(wrap);
  return { input, check };
}

/** Trimite formularul validat; erorile de salvare rămân vizibile. */
export function submitForm(form, fields, save, status, active = () => true) {
  form.noValidate = true;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;
    const values = {}; let firstInvalid = null;
    for (const [key, item] of Object.entries(fields)) { const result = item.check(); if (result.valid) values[key] = result.value; else firstInvalid ??= item.input; }
    if (firstInvalid) { firstInvalid.focus(); return; }
    form.setAttribute('aria-busy', 'true');
    try { await save(values); }
    catch (error) { if (active()) { status.textContent = error.message; status.classList.add('is-bad'); } }
    finally { if (active()) form.removeAttribute('aria-busy'); }
  });
}

/** Adaugă acțiunea de salvare. */
export function submitButton(form, text = 'Salvează') {
  const node = button(text, null, true); node.type = 'submit';
  node.dataset.focus = `submit-${form.querySelector('input')?.name ?? 'form'}`;
  form.append(node); return node;
}

/** Titlul unei secțiuni, în stilul machetei aprobate. */
export function heading(root, title, subtitle = null) {
  const head = el('header', 'shopping-heading'); head.append(el('h3', '', title));
  if (subtitle) head.append(el('p', 'shopping-sub', subtitle));
  root.append(head);
}

/** Card cu o valoare și o etichetă. */
export function metric(label, value, yellow = false) {
  const node = el('div', `shopping-metric${yellow ? ' shopping-metric--yellow' : ''}`);
  node.append(el('span', 'shopping-sub', label), el('strong', 'shopping-money', value)); return node;
}

/** Indicator semantic al bugetului, limitat numai vizual la 100%. */
export function budgetProgress(spent, budget) {
  const node = el('progress', 'shopping-progress'); node.max = 100;
  node.value = budget > 0 ? Math.min(100, Math.max(0, spent / budget * 100)) : spent > 0 ? 100 : 0;
  node.setAttribute('aria-label', 'Buget folosit'); return node;
}

/** Listează anii din raport într-un selector etichetat. */
export function yearSelect(years, selected, onChange) {
  const label = el('label', 'shopping-inline', 'Anul'); const select = el('select'); select.dataset.focus = 'year';
  for (const year of years) { const option = el('option', '', year); option.value = year; select.append(option); }
  select.value = selected; select.addEventListener('change', () => onChange(select.value)); label.append(select); return label;
}

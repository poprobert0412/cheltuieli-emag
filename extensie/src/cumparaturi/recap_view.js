// Selectarea anului și previzualizarea/exportul aceluiași card anonim.
import { button, el, heading, yearSelect } from './ui_dom.js';
import { drawRecap, downloadRecap, recapData } from './recap_export.js';

/** Montează cardul, urmărește tema și eliberează observatorul la demontare. */
export function mountRecapView(root, { insights, demo, selections, active, refresh }) {
  heading(root, 'Anul tău pe eMAG, pe un singur bon');
  const years = insights.years.map(String).sort().reverse();
  if (!years.length) { root.append(el('p', 'shopping-empty', 'Nu există ani în această analiză.')); return; }
  const year = selections.recapYear ?? years[0];
  root.append(yearSelect(years, year, (value) => { selections.recapYear = value; void refresh(); }));
  const figure = el('figure', 'shopping-recap'); const canvas = el('canvas'); canvas.id = 'shopping-recap-card';
  canvas.setAttribute('role', 'img');
  const status = el('p', 'shopping-status'); status.setAttribute('role', 'status');
  const redraw = () => {
    const data = recapData(insights.summary, year, Boolean(selections.hideSum), demo);
    const css = getComputedStyle(document.documentElement); const token = (name) => css.getPropertyValue(name).trim();
    drawRecap(canvas, data, { paper: token('--paper'), ink: token('--ink'), ink3: token('--ink-3'), hl: token('--hl'), rule: token('--rule'), rule2: token('--rule-2'), sans: token('--sans'), display: token('--display'), mono: token('--mono') });
    canvas.setAttribute('aria-label', `Bilanțul meu ${year}. ${data.orders} comenzi înregistrate. ${data.units} produse păstrate.${data.spent === null ? '' : ` Plătit efectiv: ${data.spent}.`}${demo ? ' Exemplu cu date inventate.' : ''}`);
  };
  redraw(); figure.append(canvas); root.append(figure);
  const controls = el('div', 'shopping-share-controls');
  const label = el('label', 'shopping-inline', ''); const check = el('input'); check.type = 'checkbox'; check.checked = Boolean(selections.hideSum); check.id = 'shopping-hide-sum'; check.addEventListener('change', () => { selections.hideSum = check.checked; redraw(); }); label.append(check, document.createTextNode('Ascunde suma'));
  const download = button('Descarcă imaginea', async () => {
    if (download.disabled) return; download.disabled = true;
    try { await downloadRecap(canvas, year, active); }
    catch (error) { if (active()) status.textContent = error.message; }
    finally { if (active()) download.disabled = false; }
  }, true); download.id = 'shopping-download-recap'; controls.append(label, download); root.append(controls, status);
  const observer = new MutationObserver(() => { if (active()) redraw(); }); observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  const media = matchMedia('(prefers-color-scheme: dark)'); const onTheme = () => { if (active()) redraw(); }; media.addEventListener('change', onTheme);
  return { dispose() { observer.disconnect(); media.removeEventListener('change', onTheme); } };
}

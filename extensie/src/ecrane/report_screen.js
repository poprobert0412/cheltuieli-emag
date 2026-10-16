// Ecranul „Raportul tău”: desenează raportul comun cu EmagDashboard.mount și context:'extension' (instrucțiuni potrivite extensiei), titlul cu data, descărcările și „Șterge datele” cu confirmare (portul lui app-report.js).
// Primește: tipul raportului ('saved' = ultima analiză salvată, 'demo' = analiza demonstrativă), analiza (summary) și data creării. Dă înapoi: nimic; cheamă `onNewAnalysis` și `onDeleteData`.
// La demo nu există nimic de șters și se descarcă doar raport.html și analiza.json; la analiza salvată apar toate fișierele și „Șterge datele”. Componenta se dezmontează la ieșirea din ecran (își scoate ascultătorii).
// Numele din date intră doar prin textContent, în interiorul componentei. Ce NU face: nu validează schema (o face EmagDashboard.mount), nu descarcă fișiere (download_buttons.js) și nu șterge nimic singură (main.js).
// Același bloc de ștergere poate apărea pe ecranul de eroare pentru recuperarea datelor criptate; confirmarea și ascultătorii rămân aceiași.
import { DEMO_FILES } from '../exporturi/export_files.js';

const HEADING_LEVEL = 3; // ecranul are h2 „Raportul tău”; blocurile raportului sunt h3
const DEMO_NOTE = 'Rulare de probă, cu date inventate.';

let mounted = null;
let onNewAnalysis = () => {};
let onDeleteData = () => {};

/** Mută blocul existent de ștergere pe ecranul de eroare sau îl readuce la locul lui din raport, fără duplicarea confirmării. */
export function showDataDeletionOnError(visible) {
  const { dom } = window.App;
  const block = dom.byId('data-block');
  closeDeleteConfirm(false);
  block.hidden = !visible;
  if (visible) dom.byId('screen-error').append(block);
  else dom.byId('screen-done').insertBefore(block, dom.byId('report-status'));
}

/** Ascunde butoanele de descărcare care nu se aplică acestui fel de raport. */
function showDownloadsFor(kind) {
  for (const button of document.querySelectorAll('button[data-file]')) {
    button.closest('li').hidden = kind === 'demo' && !DEMO_FILES.includes(button.getAttribute('data-file'));
  }
}

/** Închide formularul de confirmare a ștergerii; focusul se întoarce pe butonul care l-a deschis dacă se cere. */
function closeDeleteConfirm(restoreFocus) {
  const { dom } = window.App;
  const form = dom.byId('delete-confirm');
  const trigger = dom.byId('btn-delete-data');
  form.hidden = true;
  const message = dom.byId('delete-msg');
  message.className = 'field__hint session__note';
  message.textContent = '';
  trigger.setAttribute('aria-expanded', 'false');
  if (restoreFocus && !dom.byId('data-block').hidden) trigger.focus();
}

/** Deschide formularul de confirmare și mută focusul pe butonul lui de renunțare (acțiunea sigură). */
function openDeleteConfirm() {
  const { dom } = window.App;
  dom.byId('delete-confirm').hidden = false;
  dom.byId('btn-delete-data').setAttribute('aria-expanded', 'true');
  dom.byId('btn-delete-cancel').focus();
}

/** Scoate raportul din pagină și îl dezmontează. */
export function hideReport() {
  const { dom } = window.App;
  if (mounted) {
    mounted.unmount();
    mounted = null;
  }
  dom.clear(dom.byId('report-root'));
  dom.byId('report-status').textContent = '';
  dom.byId('dl-msg').textContent = '';
  closeDeleteConfirm(false);
}

/** Arată raportul: `kind` 'saved' sau 'demo'; `summary` e analiza; `createdAt` data salvării (doar la 'saved'). */
export function showReport({ kind, summary, createdAt }) {
  const { dom, format } = window.App;
  hideReport();
  const demo = kind === 'demo';
  dom.byId('done-t').textContent = 'Raportul tău';
  dom.byId('done-sub').textContent = demo ? DEMO_NOTE : `Ultima analiză: ${format.dateTime(createdAt)}.`;
  dom.byId('btn-again').textContent = demo ? 'Înapoi la început' : 'Analiză nouă';
  dom.byId('data-block').hidden = demo;
  showDownloadsFor(kind);
  const status = dom.byId('report-status');
  if (!window.EmagDashboard) {
    status.className = 'status is-bad';
    status.textContent = 'Nu am putut încărca componenta raportului (dashboard.js). Reinstalează extensia.';
    return;
  }
  status.className = 'status';
  mounted = window.EmagDashboard.mount(dom.byId('report-root'), summary, { demo, headingLevel: HEADING_LEVEL, context: 'extension' });
}

/** Leagă butoanele ecranului: „Analiză nouă” / „Înapoi la început” și „Șterge datele” cu confirmarea ei. */
export function initReportScreen(handlers) {
  const { dom } = window.App;
  onNewAnalysis = handlers.onNewAnalysis;
  onDeleteData = handlers.onDeleteData;
  dom.byId('btn-again').addEventListener('click', () => onNewAnalysis());
  dom.byId('btn-delete-data').addEventListener('click', () => {
    if (dom.byId('delete-confirm').hidden) openDeleteConfirm();
    else closeDeleteConfirm(true);
  });
  dom.byId('btn-delete-cancel').addEventListener('click', () => closeDeleteConfirm(true));
  dom.byId('delete-confirm').addEventListener('submit', (event) => {
    event.preventDefault();
    onDeleteData();
  });
}

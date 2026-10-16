// Ecranul „Analiza s-a oprit din cauza unei probleme”: mesajul în română cu „Ce faci”, „Înapoi la început” și „Descarcă jurnalul” (portul lui renderError din app-run.js).
// Primește: mesajul erorii (colectare/run_errors.js: ce s-a întâmplat + „Ce faci: …”) și dacă există un jurnal salvat de descărcat. Dă înapoi: nimic; cheamă `onBack` și `onDownloadLog`.
// Aceeași pereche de butoane are și ecranul „Analiza a fost oprită” (cancelled_screen.js), de aceea `bindEndButtons` se exportă. Mesajul intră doar prin textContent.
// Ce NU face: nu alege codul erorii (run_errors.js) și nu citește jurnalul (main.js îl dă).

// Ce se arată dacă analiza n-a dat niciun mesaj (nu ar trebui să se întâmple: classifyError întoarce mereu unul).
const FALLBACK_MESSAGE = 'Analiza nu a spus ce s-a întâmplat. Jurnalul poate ajuta: descarcă-l mai jos.';

/** Leagă „Înapoi la început” și „Descarcă jurnalul” din secțiunea `sectionId`. */
export function bindEndButtons(sectionId, { onBack, onDownloadLog }) {
  const section = window.App.dom.byId(sectionId);
  section.querySelector('[data-action="back"]').addEventListener('click', () => onBack());
  section.querySelector('[data-action="download-log"]').addEventListener('click', () => onDownloadLog());
}

/** Arată sau ascunde „Descarcă jurnalul” din secțiunea `sectionId` și șterge mesajul lui de stare. */
export function setLogButton(sectionId, available) {
  const section = window.App.dom.byId(sectionId);
  section.querySelector('[data-action="download-log"]').hidden = !available;
  setLogMessage(sectionId, '', false);
}

/** Scrie mesajul de sub butoane (ex. „A pornit descărcarea fișierului jurnal.txt”); `bad` îl face roșu. */
export function setLogMessage(sectionId, text, bad) {
  const message = window.App.dom.byId(sectionId).querySelector('[data-role="log-message"]');
  message.className = `field__hint${bad ? ' is-bad' : ''}`;
  message.textContent = text;
}

/** Leagă butoanele ecranului de eroare. */
export function initErrorScreen(handlers) {
  bindEndButtons('screen-error', handlers);
}

/** Pune mesajul erorii pe ecran și arată „Descarcă jurnalul” doar dacă există un jurnal salvat. */
export function renderError({ message, hasLog }) {
  window.App.dom.byId('error-message').textContent = message || FALLBACK_MESSAGE;
  setLogButton('screen-error', hasLog);
}

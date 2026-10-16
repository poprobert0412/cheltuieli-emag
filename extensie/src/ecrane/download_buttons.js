// Butoanele de descărcare de pe ecranul cu raportul: raport.html, produse.csv, istoric_preturi.csv, analiza.json, comenzi.json, retururi.json, jurnal.txt (portul lui app-download.js).
// Primește: clicul pe un buton cu data-file și funcția `getSource` (ce raport se arată acum: { kind: 'saved', entry } sau { kind: 'demo', summary }). Dă înapoi: nimic; salvează fișierul.
// Fișierul se construiește în pagină (exporturi/export_files.js), se face Blob și se salvează printr-un link temporar cu atributul download (exporturi/descarcare.js), fără permisiunea `downloads`.
// Ce NU face: nu alege fișiere în afara listei din export_files.js (un nume necunoscut se refuză acolo) și nu deschide fișierul descărcat.
import { downloadText } from '../exporturi/descarcare.js';
import { buildExportFile } from '../exporturi/export_files.js';

let busy = false;

/** Scrie mesajul de sub butoane (zonă live); `bad` îl face roșu. */
function setMessage(text, bad) {
  const message = window.App.dom.byId('dl-msg');
  message.className = `field__hint${bad ? ' is-bad' : ''}`;
  message.textContent = text;
}

/** Descarcă fișierul butonului apăsat; un singur fișier odată (butonul primește aria-busy). */
async function download(button, getSource) {
  if (busy) return;
  const name = button.getAttribute('data-file');
  const source = getSource();
  if (!source) {
    setMessage('Nu știu din ce raport să descarc. Închide raportul și deschide-l din nou.', true);
    return;
  }
  busy = true;
  button.setAttribute('aria-busy', 'true');
  setMessage(`Pregătesc ${name}…`, false);
  try {
    const { text, mime } = await buildExportFile(name, source);
    downloadText(name, text, mime);
    setMessage(`A pornit descărcarea fișierului ${name}. Îl găsești în folderul de descărcări al browserului.`, false);
  } catch (error) {
    setMessage(`Nu am putut descărca ${name}: ${error && error.message ? error.message : 'eroare necunoscută'}.`, true);
  } finally {
    busy = false;
    button.removeAttribute('aria-busy');
  }
}

/** Leagă butoanele de descărcare. */
export function initDownloadButtons({ getSource }) {
  for (const button of document.querySelectorAll('button[data-file]')) {
    button.addEventListener('click', () => download(button, getSource));
  }
}

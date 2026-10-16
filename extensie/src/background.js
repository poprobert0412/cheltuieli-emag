// Worker-ul din fundal al extensiei (Manifest V3): clic pe iconiță deschide sau aduce în față pagina aplicației și, când se închide fila care rula o analiză, închide fila eMAG de lucru rămasă orfană.
// Primește: clicul pe iconița extensiei și evenimentul de închidere a unei file. Dă înapoi: nimic; la clic, fila aplicației (o filă a extensiei, fără fereastră pop-up).
// Nu rulează analiza: Chrome oprește un worker după 30 s fără activitate și după 5 min pe o operație, iar o analiză durează câteva minute, deci toată munca stă în pagina aplicației; aici doar se deschide
// fila și se curăță (specificația §3). Starea nu stă în memorie: worker-ul se poate opri și reporni oricând, deci fila aplicației se caută la fiecare clic (getContexts), iar evidența lacătului e în chrome.storage.session.
// Ce NU face: nu citește pagini eMAG, nu atinge cookie-uri și nu cere permisiunea `tabs` (getContexts vede doar paginile extensiei).
import { handleTabClosed } from './stocare/run_lock.js';

const APP_PAGE = 'aplicatie.html';

/** Deschide pagina aplicației sau, dacă e deja deschisă într-o filă, o aduce în față (și fereastra ei); întoarce id-ul filei. */
export async function openOrFocusApp() {
  const url = chrome.runtime.getURL(APP_PAGE);
  const contexts = await chrome.runtime.getContexts({ contextTypes: ['TAB'], documentUrls: [url] });
  const existing = contexts.find((context) => context.tabId >= 0);
  if (existing) {
    await chrome.tabs.update(existing.tabId, { active: true });
    await chrome.windows.update(existing.windowId, { focused: true });
    return existing.tabId;
  }
  const tab = await chrome.tabs.create({ url });
  return tab.id;
}

// Ascultătorii se înregistrează la nivelul modulului (nu după un await): Chrome pornește worker-ul pentru ei și le livrează evenimentul.
chrome.action.onClicked.addListener(() => {
  openOrFocusApp().catch((error) => console.error('Cheltuieli eMAG: nu am putut deschide pagina aplicației', error));
});

chrome.tabs.onRemoved.addListener((tabId) => {
  handleTabClosed(tabId).catch((error) => console.error('Cheltuieli eMAG: curățarea după închiderea filei a eșuat', error));
});

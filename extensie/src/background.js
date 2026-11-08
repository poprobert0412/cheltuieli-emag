// Worker-ul din fundal (MV3): clicul deschide panoul pe produs sau fila aplicației în rest; închiderea filei analizei curăță fila eMAG orfană.
// Primește clicul iconiței, cererea raportului din panou și închiderea unei file. Întoarce/deschide suprafața potrivită.
// Nu rulează analiza: Chrome oprește un worker după 30 s fără activitate și după 5 min pe o operație, iar o analiză durează câteva minute, deci toată munca stă în pagina aplicației; aici doar se deschide
// fila și se curăță (specificația §3). Starea nu stă în memorie: worker-ul se poate opri și reporni oricând, deci fila aplicației se caută la fiecare clic (getContexts), iar evidența lacătului e în chrome.storage.session.
// Pe o pagină de produs autorizată deschide panoul și îi transmite o singură autorizare de citire, după clicul utilizatorului.
// Nu citește cookie-uri și nu cere permisiunea `tabs` (getContexts vede doar paginile extensiei).
import { handleTabClosed } from './stocare/run_lock.js';
import { canonicalShoppingProductUrl as productUrl } from './cumparaturi/shopping_schema.js';

const APP_PAGE = 'aplicatie.html';
export const PANEL_REQUEST_KEY = 'panou_citire_produs';

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
/** Clicul pe un produs deschide panoul în gestul utilizatorului; pe restul paginilor păstrează aplicația. */
export function handleActionClick(tab) {
  if (!productUrl(tab?.url) || !Number.isInteger(tab?.id)) return openOrFocusApp();
  // open trebuie invocat înaintea primului await: Chrome cere un gest activ al utilizatorului.
  const opening = chrome.sidePanel.open({ tabId: tab.id });
  return Promise.resolve(opening).then(() => chrome.storage.session.set({
    [PANEL_REQUEST_KEY]: { tabId: tab.id, url: tab.url, requestId: crypto.randomUUID() },
  }));
}

chrome.action.onClicked.addListener((tab) => {
  handleActionClick(tab).catch((error) => console.error('Cheltuieli eMAG: nu am putut deschide pagina aplicației', error));
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type !== 'panou-raport' || sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('sidepanel.html')) return false;
  openOrFocusApp().then(() => respond({ ok: true }), () => respond({ ok: false }));
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  handleTabClosed(tabId).catch((error) => console.error('Cheltuieli eMAG: curățarea după închiderea filei a eșuat', error));
});

// Sincronizează analiza afișată cu ștergerile și înlocuirile din alte pagini ale extensiei.
// Primește cititorul și callbacks ale ecranului; nu desenează și nu scrie în stocare.
import { LAST_ANALYSIS_KEY, loadLastAnalysis } from '../stocare/last_analysis.js';

/** Invalidează imediat datele vechi; numai ultima citire poate actualiza ecranul. Întoarce dezabonarea. */
export function watchSavedAnalysis({ onInvalidate, onLoad, onError, canReload = () => true, read = loadLastAnalysis, changes = chrome.storage.onChanged }) {
  let generation = 0;
  let disposed = false;
  const changed = (entries, area) => {
    if (area !== 'local' || !Object.hasOwn(entries, LAST_ANALYSIS_KEY)) return;
    const current = ++generation;
    if (!canReload()) return;
    onInvalidate();
    Promise.resolve().then(read).then((entry) => {
      if (!disposed && current === generation && canReload()) onLoad(entry);
    }).catch((error) => {
      if (!disposed && current === generation && canReload()) onError(error);
    });
  };
  changes.addListener(changed);
  return () => {
    disposed = true;
    generation += 1;
    changes.removeListener(changed);
  };
}

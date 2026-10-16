// Clasificarea statusului unui bloc de comandă: livrat / anulat / în curs / plătit fără livrare / necunoscut (portul lui emag_spend/block_status.py).
// Primește: textul de status afișat de eMAG pentru un vânzător dintr-o comandă. Dă înapoi: una dintre constantele de mai jos.
// Un text necunoscut dă UNKNOWN, niciodată „livrat” din greșeală: calculatorul îl raportează ca avertisment. Nu citește pagini și nu calculează sume.
import { normalizeText } from './text_normalize.js';

export const DELIVERED = 'DELIVERED'; // livrat sau ridicat (inclusiv livrat electronic)
export const CANCELLED = 'CANCELLED'; // „Livrare anulata” (anulat înainte SAU returnat și marcat anulat)
export const IN_PROGRESS = 'IN_PROGRESS'; // plasat / predat curierului / în drum: încă nelivrat
export const PAID_ONLY = 'PAID_ONLY'; // plătit fără livrare de produse (ex. asigurări)
export const UNKNOWN = 'UNKNOWN';

// Ordinea contează: prima regulă potrivită câștigă. „Livrare anulata” bate orice, fiindcă mesajul „Am trimis cererea de anulare...”
// precede confirmarea „Livrare anulata” în același bloc. „ajunse in/la” = ajunse la punctul de ridicare, dar neridicate încă;
// după ridicare eMAG afișează „Produse ridicate”, regula de mai sus.
const RULES = [
  ['livrare anulata', CANCELLED],
  ['produse ridicate', DELIVERED],
  ['produse livrate', DELIVERED],
  ['plata acceptata', PAID_ONLY],
  ['comanda plasata', IN_PROGRESS],
  ['predate curierului', IN_PROGRESS],
  ['in drum spre', IN_PROGRESS],
  ['ajunse in', IN_PROGRESS],
  ['ajunse la', IN_PROGRESS],
  ['in curs de', IN_PROGRESS],
  ['in pregatire', IN_PROGRESS],
  ['pregatit', IN_PROGRESS],
  ['expediat', IN_PROGRESS],
  ['confirmat', IN_PROGRESS],
];

/** Clasa blocului după textul de status (vezi constantele din modul); textul se normalizează întâi (fără diacritice, litere mici). */
export function classifyStatus(statusText) {
  const normalized = normalizeText(statusText);
  for (const [needle, status] of RULES) {
    if (normalized.includes(needle)) return status;
  }
  return UNKNOWN;
}

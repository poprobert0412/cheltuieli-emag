// Eroarea „pagina nu arată cum se așteaptă extensia”: lipsește „Comanda nr.” sau „Retur #”, lista e goală, un parser a refuzat pagina.
// Primește: unde s-a întâmplat (lista de comenzi, calea unei pagini de detalii) și motivul scurt. Dă înapoi: o excepție cu codul stabil `page_changed`.
// Mesajul păstrează locul și motivul (pentru jurnal); câmpul `reason` e doar motivul, fără număr de comandă, pentru ecranul de eroare (run_errors.js).
// Ce NU face: nu citește pagini și nu decide ce se întâmplă mai departe.
import { CODE_PAGE_CHANGED } from './run_errors.js';

/** Pagina cerută nu are forma așteptată (eMAG și-a schimbat paginile sau pagina nu s-a încărcat). */
export class PageChanged extends Error {
  /** `where`: locul (ex. „lista de comenzi” sau calea paginii); `reason`: motivul scurt, în română. */
  constructor(where, reason) {
    super(`${where}: ${reason}`);
    this.name = 'PageChanged';
    this.code = CODE_PAGE_CHANGED;
    this.where = where;
    this.reason = reason;
  }
}

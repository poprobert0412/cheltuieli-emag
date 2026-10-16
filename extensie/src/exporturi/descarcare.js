// Descărcarea unui fișier din pagina extensiei: Blob + link ascuns cu atributul download, fără permisiunea `downloads`.
// Primește: numele fișierului, textul lui și tipul MIME. Dă înapoi: nimic; browserul salvează fișierul în folderul de descărcări.
// Linkul are doar o adresă blob: din memoria paginii (nu o adresă de rețea); adresa se revocă după REVOKE_DELAY_MS ca să nu rămână în memorie.
// Textul se codifică în UTF-8 așa cum e: un BOM de la început (CSV-urile pentru Excel) rămâne în octeți.
// Ce NU face: nu construiește conținutul fișierelor (export_files.js) și nu deschide fișierul descărcat.

// Cât ținem adresa blob: vie după clic. Firefox are nevoie de câteva secunde ca să înceapă salvarea; după aceea se eliberează memoria (aceeași valoare ca în aplicația locală, app-download.js).
export const REVOKE_DELAY_MS = 10_000;

/** Salvează `text` ca fișierul `fileName` (tip `mimeType`). `env` e pentru teste: document, URL și setTimeout false. */
export function downloadText(fileName, text, mimeType, env = {}) {
  const doc = env.document ?? document;
  const urlApi = env.URL ?? URL;
  const defer = env.setTimeout ? env.setTimeout.bind(env) : setTimeout;
  const url = urlApi.createObjectURL(new Blob([text], { type: mimeType }));
  const link = doc.createElement('a');
  link.href = url;
  link.download = fileName;
  link.hidden = true;
  doc.body.appendChild(link);
  link.click();
  link.remove();
  defer(() => urlApi.revokeObjectURL(url), REVOKE_DELAY_MS);
}

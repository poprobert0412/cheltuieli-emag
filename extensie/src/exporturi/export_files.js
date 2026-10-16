// Construiește textul fiecărui fișier descărcabil din raport: raport.html, produse.csv, istoric_preturi.csv, analiza.json, comenzi.json, retururi.json, jurnal.txt.
// Primește: numele fișierului și sursa: { kind: 'saved', entry } (ultima analiză salvată) sau { kind: 'demo', summary } (analiza demonstrativă). Dă înapoi: { text, mime }.
// Modulele de export (csv_export, price_history_csv, report_html) și analiza se încarcă abia la descărcare, cu import dinamic cu cale literală. produse.csv are nevoie de registrul de linii, care NU se păstrează (E4:
// doar cifrele, comenzile și retururile): se recalculează din comenzile și retururile salvate, cu pragul și data salvate. La demo se descarcă doar raport.html și analiza.json.
// Ce NU face: nu salvează fișierul în browser (descarcare.js) și nu știe de butoane sau de ecrane.
import { pyJsonDumps, pyRoundInt } from '../calcul/python_compat.js';
import { loadAnalysis } from '../rulare/analysis_loader.js';

export const REAL_FILES = Object.freeze(['raport.html', 'produse.csv', 'istoric_preturi.csv', 'analiza.json', 'comenzi.json', 'retururi.json', 'jurnal.txt']);
export const DEMO_FILES = Object.freeze(['raport.html', 'analiza.json']);

const MIME_TYPES = Object.freeze({
  '.html': 'text/html;charset=utf-8',
  '.csv': 'text/csv;charset=utf-8',
  '.json': 'application/json;charset=utf-8',
  '.txt': 'text/plain;charset=utf-8',
});
// Câte caractere din data creării intră în „generated_at” al analizei: „2026-10-14 09:30” (fără secunde), ca f"{datetime.now():%Y-%m-%d %H:%M}" din run_pipeline.py.
const GENERATED_AT_CHARS = 16;

// Încărcătoarele reale ale modulelor de export (căi literale); testele dau altele.
const DEFAULT_LOADERS = Object.freeze({
  reportSource: () => import('../generat/raport_sursa.js'),
  reportHtml: () => import('./report_html.js'),
  csvExport: () => import('./csv_export.js'),
  priceHistoryCsv: () => import('./price_history_csv.js'),
  analysis: () => loadAnalysis(),
});

/** Tipul MIME al fișierului după extensie. */
export function mimeTypeOf(fileName) {
  const mime = MIME_TYPES[fileName.slice(fileName.lastIndexOf('.'))];
  if (!mime) throw new RangeError(`tip de fișier necunoscut: ${fileName}`);
  return mime;
}

/** Analiza (cifrele raportului) din sursă: cea salvată sau cea demonstrativă. */
function summaryOf(source) {
  return source.kind === 'demo' ? source.summary : source.entry.summary;
}

/** Textul lui `fileName` pentru `source`; RangeError dacă numele nu e permis pentru acest fel de sursă (la demo doar DEMO_FILES). */
export async function buildExportFile(fileName, source, loaders = DEFAULT_LOADERS) {
  const allowed = source.kind === 'demo' ? DEMO_FILES : REAL_FILES;
  if (!allowed.includes(fileName)) throw new RangeError(`${fileName} nu se poate descărca${source.kind === 'demo' ? ' din raportul demonstrativ' : ''}`);
  const summary = summaryOf(source);
  const mime = mimeTypeOf(fileName);
  switch (fileName) {
    case 'raport.html': {
      const [{ default: report }, { buildReport }] = await Promise.all([loaders.reportSource(), loaders.reportHtml()]);
      return { text: buildReport(report.template, report.css, report.js, summary, { context: 'extension', appName: report.appName }), mime };
    }
    case 'analiza.json':
      return { text: pyJsonDumps(summary, { fractions: true }), mime };
    case 'comenzi.json':
      return { text: pyJsonDumps(source.entry.orders), mime };
    case 'retururi.json':
      return { text: pyJsonDumps(source.entry.returns), mime };
    case 'jurnal.txt':
      return { text: source.entry.log_text, mime };
    case 'istoric_preturi.csv': {
      const { priceHistoryCsv } = await loaders.priceHistoryCsv();
      return { text: priceHistoryCsv(summary.price_history), mime };
    }
    case 'produse.csv': {
      const { entry } = source;
      const thresholdBani = pyRoundInt(entry.threshold_lei * 100);
      const [analysis, { linesCsv }] = await Promise.all([loaders.analysis(), loaders.csvExport()]);
      const { lines } = analysis.analyze(entry.orders, entry.returns, thresholdBani, entry.created_at.slice(0, GENERATED_AT_CHARS));
      return { text: linesCsv(lines, thresholdBani), mime };
    }
    default:
      throw new RangeError(`fișier necunoscut: ${fileName}`);
  }
}

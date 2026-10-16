// Încarcă analiza (leneș) și o leagă de configurările generate la build: întoarce `analyze(orders, returns, thresholdBani, generatedAt, log)` și `plainSummary(summary)`, gata de apelat.
// Primește: nimic (în teste, încărcătoare false). Dă înapoi: { analyze, plainSummary } sau o eroare cu mesajul din Python dacă o configurare e greșită.
// Modulele analizei (spend_analysis, classifier, warning_details, product_key, refund_modes) se încarcă abia aici, cu import dinamic cu cale literală: pagina pornește fără ele și le aduce la „Pornește analiza”.
// Ca în run_pipeline.py, regulile de categorii, textele avertismentelor, culorile și modurile de restituire se verifică ÎNAINTE de colectare: o greșeală oprește rularea în secunde, nu după minute.
// Configurările vin din dist/generat/config.js (scris de scripts/build.mjs din config/*.json, fără regulile personale de categorii, care nu intră în v1).
// `log` (RunLog) ajunge la analiză, ca mesajele ei să intre în jurnalul rulării; `plainSummary` e copia fără PyFloat, singura formă care se salvează și se desenează (vezi run_pipeline.js).
import { HIGHLIGHT_CATEGORIES } from '../settings.js';

// Numele fișierelor din config/, ca în mesajele de eroare ale programului Python (care citează path.name).
const CATEGORIES_SOURCE = 'categorii.json';
const WARNINGS_SOURCE = 'avertismente.json';
const COLORS_SOURCE = 'culori.json';
const REFUND_MODES_SOURCE = 'restituiri.json';

// Încărcătoarele reale: fiecare modul are cale literală (garda interzice importul dinamic cu cale calculată). Testele dau altele.
const DEFAULT_LOADERS = Object.freeze({
  config: () => import('../generat/config.js'),
  spendAnalysis: () => import('../calcul/spend_analysis.js'),
  classifier: () => import('../calcul/classifier.js'),
  warningDetails: () => import('../calcul/warning_details.js'),
  productKey: () => import('../calcul/product_key.js'),
  refundModes: () => import('../calcul/refund_modes.js'),
});

/**
 * Încarcă și verifică tot ce are nevoie analiza. Aruncă (Error cu mesajul din Python) dacă o regulă sau un text de configurare e greșit,
 * sau dacă o categorie evidențiată (settings.HIGHLIGHT_CATEGORIES) nu există în reguli: altfel raportul ar arăta „0,00 Lei, niciun produs” la ea.
 */
export async function loadAnalysis(loaders = DEFAULT_LOADERS) {
  const [config, spend, classifierModule, warnings, productKey, refundModes] = await Promise.all([
    loaders.config(), loaders.spendAnalysis(), loaders.classifier(), loaders.warningDetails(), loaders.productKey(), loaders.refundModes(),
  ]);
  const settings = config.default;
  const classifier = new classifierModule.Classifier(settings.categorii, CATEGORIES_SOURCE);
  const known = new Set([...classifier.categoryNames, classifier.defaultCategory]); // și „Necategorizat” are totaluri reale
  const missing = HIGHLIGHT_CATEGORIES.filter((name) => !known.has(name));
  if (missing.length > 0) {
    throw new Error(
      `categoria evidențiată ${missing.map((name) => `«${name}»`).join(', ')} nu există în ${CATEGORIES_SOURCE}: `
      + 'adaug-o în reguli sau scoate-o din HIGHLIGHT_CATEGORIES (extensie/src/settings.js)',
    );
  }
  const warningTexts = warnings.loadWarningTexts(settings.avertismente, WARNINGS_SOURCE);
  const colorWords = productKey.loadColorWords(settings.culori, COLORS_SOURCE);
  const refundModeRules = refundModes.loadRefundModes(settings.restituiri, REFUND_MODES_SOURCE);
  return {
    /**
     * { summary, lines } pentru comenzile și retururile date; `thresholdBani` e pragul în bani, `generatedAt` data în forma „2026-10-14 09:30”.
     * `log` (RunLog, opțional): primește rândurile analizei (potrivirea retururilor, avertismente). Capcană: `summary` are procentele ca PyFloat; pentru salvare și ecran trece prin `plainSummary`.
     */
    analyze(orders, returns, thresholdBani, generatedAt, log = null) {
      return spend.analyze(orders, returns, classifier, thresholdBani, generatedAt, {
        highlightCategories: HIGHLIGHT_CATEGORIES, warningTexts, colorWords, refundModes: refundModeRules, log,
      });
    },
    /** Copia rezumatului numai din tipuri JSON simple (fiecare PyFloat devine numărul lui): chrome.storage ar păstra un PyFloat ca obiect, iar dashboard.js cere numere. */
    plainSummary: spend.plainSummary,
  };
}

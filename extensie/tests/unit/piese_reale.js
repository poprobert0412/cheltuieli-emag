// Piesele reale ale proiectului pe care le folosesc testele unitare ca să nu se bazeze pe copii: modulele analizei cu configurările din config/, și sursele raportului
// (designul din interfata/assets/, șablonul din templates/, rezumatul de demonstrație) cu validatorul real al raportului, încărcat într-un context node:vm ca scripturile clasice din pagină.
// Primește: nimic. Dă înapoi: încărcătoare pentru loadAnalysis (`realAnalysisLoaders`) și sursele raportului (`loadReportAssets`).
// Ce NU face: nu rulează teste (de aceea numele nu se termină în .test.js) și nu citește nimic din afara depozitului.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const ASSETS_DIR = path.join(REPO_ROOT, 'interfata', 'assets');
const CONFIG_DIR = path.join(REPO_ROOT, 'config');
const TEMPLATE_FILE = path.join(REPO_ROOT, 'templates', 'raport.html');

/** Încărcătoare reale pentru `loadAnalysis`: modulele analizei din calcul/ și configurările din config/ (ca dist/generat/config.js, fără regulile personale de categorii). */
export function realAnalysisLoaders() {
  const readConfig = (name) => JSON.parse(readFileSync(path.join(CONFIG_DIR, name), 'utf8'));
  return {
    config: async () => ({
      default: { categorii: readConfig('categorii.json'), avertismente: readConfig('avertismente.json'), culori: readConfig('culori.json'), restituiri: readConfig('restituiri.json') },
    }),
    spendAnalysis: () => import('../../src/calcul/spend_analysis.js'),
    classifier: () => import('../../src/calcul/classifier.js'),
    warningDetails: () => import('../../src/calcul/warning_details.js'),
    productKey: () => import('../../src/calcul/product_key.js'),
    refundModes: () => import('../../src/calcul/refund_modes.js'),
  };
}

/**
 * Sursele raportului: `validate` (validatorul real, interfata/assets/dashboard.js), `demoSummary` (rezumatul de demonstrație, JSON simplu, o copie nouă la fiecare apel)
 * și `reportSource` ({ appName, template, css, js }, ca în dist/generat/raport_sursa.js, cu numele din manifest). Capcană: `validate` întoarce obiecte din contextul vm, deci rezultatul se compară prin JSON, nu cu deepEqual.
 */
export function loadReportAssets() {
  const sandbox = {};
  sandbox.window = sandbox;
  const context = vm.createContext(sandbox);
  const dashboardJs = readFileSync(path.join(ASSETS_DIR, 'dashboard.js'), 'utf8');
  vm.runInContext(dashboardJs, context, { filename: 'dashboard.js' });
  vm.runInContext(readFileSync(path.join(ASSETS_DIR, 'demo-data.js'), 'utf8'), context, { filename: 'demo-data.js' });
  const demoText = JSON.stringify(sandbox.EMAG_DEMO_DATA);
  return {
    validate: sandbox.EmagDashboard.validate,
    demoSummary: () => JSON.parse(demoText),
    reportSource: {
      appName: JSON.parse(readFileSync(path.join(REPO_ROOT, 'extensie', 'manifest.json'), 'utf8')).name,
      template: readFileSync(TEMPLATE_FILE, 'utf8'),
      css: readFileSync(path.join(ASSETS_DIR, 'dashboard.css'), 'utf8'),
      js: dashboardJs,
    },
  };
}

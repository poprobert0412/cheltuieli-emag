// build.mjs — construiește extensia gata de încărcat în dist/ și arhiva ei (cheltuieli-emag-<versiune>.zip), fără dependențe.
// Primește: nimic (calea implicită: extensie/dist), sau --strict (modulele încărcate leneș trebuie să existe) și --out <folder>. Dă înapoi: dist/ cu manifestul, src/**, sursele unice copiate din interfata/ și config/, LICENSE și arhiva.
// Sursele unice rămân unde sunt (E7): interfata/assets/ (raportul și designul ecranelor), config/*.json, templates/raport.html; build-ul doar le copiază în dist/partajat/ și le scrie ca module în dist/generat/
// (config.js, raport_sursa.js), ca extensia să nu facă nicio cerere nici la propriile fișiere. Regulile personale de categorii (config/categorii.personal.json) NU intră în v1 (specificația §12).
// Verifică la sfârșit: fiecare fișier cerut de manifest și de aplicatie.html există, iar fiecare import relativ are țintă (cele încărcate leneș cu import() lipsă dau avertisment; cu --strict, eroare).
// Ce NU face: nu rulează teste, nu minifică și nu publică nimic.
import {
  cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync,
} from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { listFiles, zipDirectory } from './zip.mjs';

export const EXTENSION_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const PROJECT_ROOT = path.resolve(EXTENSION_DIR, '..');
export const DIST_DIR = path.join(EXTENSION_DIR, 'dist');

// Fișierele din interfata/assets/ pe care le folosește extensia, în dist/partajat/: raportul (dashboard), designul ecranelor, scripturile mici ale ecranelor care nu depind de serverul local și analiza demonstrativă.
const SHARED_ASSETS = Object.freeze([
  'dashboard.js', 'dashboard.css', 'app.css', 'app-theme.js', 'app-dom.js', 'app-format.js', 'app-threshold.js', 'demo-data.js',
]);
// Configurările publice (cheia din modulul generat -> fișierul din config/). categorii.personal.json lipsește intenționat.
const CONFIG_FILES = Object.freeze({
  categorii: 'categorii.json', avertismente: 'avertismente.json', culori: 'culori.json', restituiri: 'restituiri.json',
});
const REPORT_TEMPLATE = path.join('templates', 'raport.html');
const APP_PAGE = 'aplicatie.html';
const BOM = String.fromCharCode(0xfeff);
// Importuri relative într-un fișier JS: statice (import ... from, export ... from, import 'x') și dinamice cu cale literală (import('x')).
const STATIC_IMPORT = /(?:^|\n)\s*(?:import|export)\s[^'"`;]*?from\s*['"]([^'"]+)['"]/g;
const BARE_IMPORT = /(?:^|\n)\s*import\s*['"]([^'"]+)['"]/g;
const DYNAMIC_IMPORT = /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g;
const HTML_REFERENCE = /\b(?:src|href)="([^"]+)"/g;

/** Citește un fișier text UTF-8; un BOM de la început (Notepad îl scrie la JSON-uri) se scoate. */
function readText(file) {
  const text = readFileSync(file, 'utf8');
  return text.startsWith(BOM) ? text.slice(BOM.length) : text;
}

/** Toate valorile text din `value` (un obiect cu căi de fișiere, ca `icons`) sau `value` însuși dacă e text. */
function pathsIn(value) {
  if (typeof value === 'string') return [value];
  if (value && typeof value === 'object') return Object.values(value).flatMap(pathsIn);
  return [];
}

/** Fișierele cerute de manifest (worker-ul și iconițele) trebuie să existe în `outDir`. */
function checkManifestFiles(outDir, manifest) {
  const required = [manifest.background?.service_worker, ...pathsIn(manifest.action?.default_icon), ...pathsIn(manifest.icons)].filter(Boolean);
  for (const relative of required) {
    if (!existsSync(path.join(outDir, relative))) throw new Error(`manifestul cere ${relative}, dar fișierul lipsește din ${outDir}`);
  }
}

/** Referințele din aplicatie.html (src și href) trebuie să existe în `outDir`; o adresă externă e eroare (CSP-ul ar bloca-o oricum). */
function checkHtmlReferences(outDir) {
  const html = readFileSync(path.join(outDir, APP_PAGE), 'utf8');
  for (const [, reference] of html.matchAll(HTML_REFERENCE)) {
    if (reference.startsWith('#') || reference.startsWith('data:')) continue;
    if (/^(?:[a-z]+:)?\/\//i.test(reference)) throw new Error(`${APP_PAGE} cere o resursă externă: ${reference}`);
    if (!existsSync(path.join(outDir, reference.split('#')[0]))) throw new Error(`${APP_PAGE} cere ${reference}, dar fișierul lipsește din ${outDir}`);
  }
}

/** Specificatorii de import ai unui text JS: { statici, dinamici }. */
function importsOf(text) {
  const statics = [...text.matchAll(STATIC_IMPORT), ...text.matchAll(BARE_IMPORT)].map((match) => match[1]);
  const dynamics = [...text.matchAll(DYNAMIC_IMPORT)].map((match) => match[1]);
  return { statics, dynamics };
}

/**
 * Fiecare import relativ din modulele extensiei trebuie să aibă țintă în `outDir`. Un import ne-relativ e eroare (în browser nu se rezolvă); unul static lipsă, eroare;
 * unul dinamic lipsă (modulele încărcate leneș: parsere, analiză, exporturi), avertisment, sau eroare cu `strict`. Întoarce avertismentele.
 */
function checkImports(outDir, files, strict) {
  const warnings = [];
  const modules = files.filter((name) => name.endsWith('.js') && !name.startsWith('partajat/'));
  for (const name of modules) {
    const { statics, dynamics } = importsOf(readFileSync(path.join(outDir, name), 'utf8'));
    for (const [specifiers, dynamic] of [[statics, false], [dynamics, true]]) {
      for (const specifier of specifiers) {
        if (!specifier.startsWith('./') && !specifier.startsWith('../')) throw new Error(`${name}: importul «${specifier}» nu e relativ, deci nu se rezolvă în extensie`);
        const target = path.relative(outDir, path.resolve(outDir, path.dirname(name), specifier)).split(path.sep).join('/');
        if (existsSync(path.join(outDir, target))) continue;
        const message = `${name}: importul «${specifier}» nu are țintă (${target})`;
        if (dynamic && !strict) warnings.push(message);
        else throw new Error(message);
      }
    }
  }
  return warnings;
}

/** Scrie un modul JS cu `export default <valoare>`: JSON-ul e și JavaScript valid, deci valoarea intră ca literal, fără cod de interpretat. */
function writeDefaultExport(file, value) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `export default ${JSON.stringify(value)};\n`, 'utf8');
}

/**
 * Construiește extensia în `outDir` (implicit extensie/dist) și arhiva ei. `extensionDir` și `projectRoot` se pot schimba în teste; `strict` face din avertismente erori.
 * Întoarce { outDir, version, zipPath, files, warnings }; aruncă Error cu mesaj în română la prima problemă.
 */
export function build({
  outDir = DIST_DIR, extensionDir = EXTENSION_DIR, projectRoot = PROJECT_ROOT, strict = false,
} = {}) {
  const manifestFile = path.join(extensionDir, 'manifest.json');
  const manifest = JSON.parse(readText(manifestFile));
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  cpSync(manifestFile, path.join(outDir, 'manifest.json'));
  cpSync(path.join(extensionDir, 'src'), outDir, { recursive: true, filter: (source) => !path.basename(source).startsWith('.') });
  cpSync(path.join(projectRoot, 'LICENSE'), path.join(outDir, 'LICENSE'));

  for (const name of SHARED_ASSETS) {
    const source = path.join(projectRoot, 'interfata', 'assets', name);
    if (!existsSync(source)) throw new Error(`lipsește sursa unică ${source}`);
    cpSync(source, path.join(outDir, 'partajat', name));
  }
  const config = Object.fromEntries(Object.entries(CONFIG_FILES).map(([key, name]) => [key, JSON.parse(readText(path.join(projectRoot, 'config', name)))]));
  writeDefaultExport(path.join(outDir, 'generat', 'config.js'), config);
  writeDefaultExport(path.join(outDir, 'generat', 'raport_sursa.js'), {
    appName: manifest.name,
    template: readText(path.join(projectRoot, REPORT_TEMPLATE)),
    css: readText(path.join(projectRoot, 'interfata', 'assets', 'dashboard.css')),
    js: readText(path.join(projectRoot, 'interfata', 'assets', 'dashboard.js')),
  });

  checkManifestFiles(outDir, manifest);
  checkHtmlReferences(outDir);
  const warnings = checkImports(outDir, listFiles(outDir), strict);

  const zipName = `cheltuieli-emag-${manifest.version}.zip`;
  const zipPath = path.join(outDir, zipName);
  const files = zipDirectory(outDir, zipPath); // outDir a fost golit la început, deci arhiva nu apare în propria listă
  return { outDir, version: manifest.version, zipPath, files, warnings };
}

/** Linia de comandă: `node scripts/build.mjs [--strict] [--out <folder>]`. */
function main(argv) {
  const strict = argv.includes('--strict');
  const outIndex = argv.indexOf('--out');
  const outDir = outIndex >= 0 ? path.resolve(argv[outIndex + 1]) : DIST_DIR;
  const result = build({ outDir, strict });
  for (const warning of result.warnings) console.warn(`avertisment: ${warning}`);
  console.log(`extensie construită în ${result.outDir}: ${result.files.length} fișiere, versiunea ${result.version}`);
  console.log(`arhivă: ${result.zipPath}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`eroare: ${error && error.message ? error.message : error}`);
    process.exitCode = 1;
  }
}

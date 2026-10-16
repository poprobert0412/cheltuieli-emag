// Teste unitare pentru build-ul extensiei (scripts/build.mjs, scripts/zip.mjs) și pentru manifest, pagina aplicației și iconițe.
// Verifică: manifestul are exact permisiunile din specificație (§3) și nimic în plus; build-ul copiază sursele unice neschimbate (E7), scrie configurările ca module fără regulile personale, închide verificările
// (fișiere cerute de manifest și de pagină, importuri relative) și face o arhivă deterministă pe care Python o deschide (`zipfile.testzip`), cu fișierele din dist/ și manifestul în rădăcină.
// Iconițele livrate se decodează pixel cu pixel (bonul pe pătratul deschis cu colțuri rotunjite, 16 px transparenți pe margini la 128: regula magazinului).
// Construirea rulează într-un folder temporar, nu atinge extensie/dist. Ce NU face: nu încarcă extensia în browser (asta e verificarea din Edge).
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { pathToFileURL } from 'node:url';

import { EXTENSION_DIR, PROJECT_ROOT, build } from '../../scripts/build.mjs';
import { listFiles } from '../../scripts/zip.mjs';
import { decodePng } from './png_decoder.js';

const MANIFEST = JSON.parse(readFileSync(path.join(EXTENSION_DIR, 'manifest.json'), 'utf8'));
const APP_HTML_FILE = path.join(EXTENSION_DIR, 'src', 'aplicatie.html');
const APP_HTML = readFileSync(APP_HTML_FILE, 'utf8');
const BOM_AT_START = new RegExp(`^${String.fromCharCode(0xfeff)}`);
const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
// Limitele magazinului Chrome pentru câmpurile din manifest (name până la 75 de caractere, description până la 132), numărate în caractere.
const MAX_NAME_CHARS = 75;
const MAX_DESCRIPTION_CHARS = 132;
// Cheile de manifest care ar lărgi suprafața extensiei (script pe pagini, resurse expuse paginilor, acces din afară, CSP schimbat): specificația §3 le interzice.
const FORBIDDEN_MANIFEST_KEYS = [
  'content_scripts', 'web_accessible_resources', 'externally_connectable', 'optional_permissions', 'optional_host_permissions', 'content_security_policy',
  'commands', 'omnibox', 'chrome_url_overrides', 'devtools_page', 'update_url', 'sandbox', 'declarative_net_request', 'side_panel',
];

const scratch = [];
/** Un folder temporar, șters la final. */
function tempDir(prefix) {
  const dir = mkdtempSync(path.join(tmpdir(), `${prefix}-`));
  scratch.push(dir);
  return dir;
}
after(() => {
  for (const dir of scratch) rmSync(dir, { recursive: true, force: true });
});

/** Suma SHA-256 a unui fișier. */
function sha256(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

describe('manifest: exact permisiunile din specificație (§3), fără nimic în plus', () => {
  test('Manifest V3, Chrome 120 sau mai nou', () => {
    assert.equal(MANIFEST.manifest_version, 3);
    assert.equal(MANIFEST.minimum_chrome_version, '120');
  });

  test('permisiuni: exact „storage” și „scripting”; acces la gazde: exact https://www.emag.ro/*', () => {
    assert.deepEqual([...MANIFEST.permissions].sort(), ['scripting', 'storage']);
    assert.deepEqual(MANIFEST.host_permissions, ['https://www.emag.ro/*']);
  });

  test('fără chei care ar lărgi extensia: content_scripts, web_accessible_resources, externally_connectable, CSP schimbat...', () => {
    for (const key of FORBIDDEN_MANIFEST_KEYS) assert.ok(!(key in MANIFEST), `manifestul are cheia interzisă ${key}`);
  });

  test('clicul pe iconiță deschide direct fila aplicației: fără fereastră pop-up', () => {
    assert.ok(!('default_popup' in MANIFEST.action));
    assert.equal(MANIFEST.background.service_worker, 'background.js');
    assert.equal(MANIFEST.background.type, 'module');
  });

  test('versiunea e a manifestului (sursa unică, E8): 1–4 numere separate prin punct', () => {
    assert.match(MANIFEST.version, /^\d+(?:\.\d+){0,3}$/);
  });

  test('numele aprobat pe 16.10.2026 este exact cel ales de Robert; descrierea încape și păstrează neafilierea', () => {
    assert.equal(MANIFEST.name, 'Cât am cheltuit pe eMAG');
    assert.ok([...MANIFEST.name].length <= MAX_NAME_CHARS);
    assert.ok([...MANIFEST.description].length <= MAX_DESCRIPTION_CHARS, `descrierea are ${[...MANIFEST.description].length} de caractere`);
    assert.match(MANIFEST.description, /Neafiliat/);
  });

  test('toate iconițele din manifest sunt PNG-uri RGBA de exact mărimea din nume', () => {
    const declared = new Set([...Object.values(MANIFEST.icons), ...Object.values(MANIFEST.action.default_icon)]);
    assert.ok(declared.size >= 4);
    for (const relative of declared) {
      const file = path.join(EXTENSION_DIR, 'src', relative);
      assert.ok(existsSync(file), `lipsește ${relative}`);
      const bytes = readFileSync(file);
      assert.deepEqual([...bytes.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], `${relative} nu e PNG`);
      const size = Number(/icon-(\d+)\.png$/.exec(relative)[1]);
      assert.equal(bytes.readUInt32BE(16), size, `${relative}: lățime greșită`);
      assert.equal(bytes.readUInt32BE(20), size, `${relative}: înălțime greșită`);
      assert.equal(bytes[24], 8, `${relative}: nu e pe 8 biți`);
      assert.equal(bytes[25], 6, `${relative}: nu e RGBA (transparență)`);
    }
  });
});

describe('iconițele: bonul pe un pătrat deschis cu colțuri rotunjite (varianta B, aprobată de Robert)', () => {
  const ICON_SIZES = [16, 32, 48, 128];
  const STORE_ICON_SIZE = 128;
  // La 128 px pătratul are 96 px, cu 16 px transparenți pe fiecare parte (regula magazinului Chrome); la celelalte mărimi umple toată imaginea.
  const STORE_MARGIN = 16;
  const icon = (size) => decodePng(readFileSync(path.join(EXTENSION_DIR, 'src', 'iconite', `icon-${size}.png`)));
  // Hârtia e „deschisă” (fiecare canal peste 0xe0), cerneala bonului „închisă” (sub 0x40), linia lui „galbenă” (roșu și verde mari, albastru mic): culorile exacte sunt ale generatorului, nu ale testului.
  const isPaper = ([r, g, b, a]) => a === 255 && r > 0xe0 && g > 0xe0 && b > 0xe0;
  const isInk = ([r, g, b, a]) => a === 255 && r < 0x40 && g < 0x40 && b < 0x40;
  const isYellow = ([r, g, b, a]) => a === 255 && r > 0xe0 && g > 0xc0 && b < 0xa0;

  /** Dreptunghiul în care există pixeli vizibili (alfa > 0): { minX, maxX, minY, maxY }. */
  function visibleBox(image) {
    const box = { minX: image.width, maxX: -1, minY: image.height, maxY: -1 };
    for (let y = 0; y < image.height; y += 1) {
      for (let x = 0; x < image.width; x += 1) {
        if (image.pixel(x, y)[3] === 0) continue;
        box.minX = Math.min(box.minX, x);
        box.maxX = Math.max(box.maxX, x);
        box.minY = Math.min(box.minY, y);
        box.maxY = Math.max(box.maxY, y);
      }
    }
    return box;
  }

  for (const size of ICON_SIZES) {
    const margin = size === STORE_ICON_SIZE ? STORE_MARGIN : 0;
    const tile = size - 2 * margin;

    test(`icon-${size}: pătratul ocupă exact ${tile} px${margin ? `, cu ${margin} px transparenți pe fiecare parte` : ' (toată imaginea)'}`, () => {
      assert.deepEqual(visibleBox(icon(size)), { minX: margin, maxX: size - 1 - margin, minY: margin, maxY: size - 1 - margin });
    });

    test(`icon-${size}: colțurile sunt rotunjite (pixelul din colț e transparent), iar mijlocul laturii e hârtie`, () => {
      const image = icon(size);
      assert.ok(image.pixel(margin, margin)[3] < 128, 'colțul trebuie să fie în afara arcului');
      assert.ok(image.pixel(size - 1 - margin, size - 1 - margin)[3] < 128);
      assert.ok(isPaper(image.pixel(size >> 1, margin)), 'mijlocul laturii de sus trebuie să fie hârtie deschisă');
      assert.ok(isPaper(image.pixel(margin, size >> 1)), 'mijlocul laturii din stânga trebuie să fie hârtie deschisă');
    });
  }

  for (const size of [32, 48, STORE_ICON_SIZE]) {
    test(`icon-${size}: bonul e în mijloc: corpul închis la centru, linia galbenă deasupra lui`, () => {
      const image = icon(size);
      const margin = size === STORE_ICON_SIZE ? STORE_MARGIN : 0;
      const scale = (size - 2 * margin) / 32; // unități de viewBox -> pixeli
      assert.ok(isInk(image.pixel(size >> 1, size >> 1)), 'centrul trebuie să fie corpul închis al bonului');
      // Prima linie a bonului (y = 9 în desenul de 32): după micșorarea la 75% și marginea de 4 unități ajunge la 4 + 0,75 * 9 unități de sus.
      const lineRow = Math.floor(margin + (4 + 0.75 * 9) * scale);
      assert.ok(isYellow(image.pixel(size >> 1, lineRow)), `linia galbenă trebuie să fie la rândul ${lineRow}`);
    });
  }

  test('tileSvg păstrează desenul bonului din favicon cuvânt cu cuvânt și îl pune pe pătratul rotunjit', async () => {
    const { receiptSvg, tileSvg } = await import('../../scripts/iconite.mjs');
    const receipt = receiptSvg();
    const inner = receipt.slice(receipt.indexOf('>') + 1, receipt.lastIndexOf('</svg>'));
    const tileMarkup = tileSvg(receipt);
    assert.ok(tileMarkup.includes(inner), 'desenul bonului nu trebuie schimbat');
    assert.match(tileMarkup, /<rect [^>]*rx="\d+"/);
    assert.ok(tileMarkup.indexOf('<rect') < tileMarkup.indexOf(inner), 'pătratul e dedesubt, bonul deasupra');
  });

  test('tileSvg refuză un favicon care nu mai e un svg cu viewBox-ul 0 0 32 32 (bonul ar ieși strâmb pe pătrat, fără nicio eroare)', async () => {
    const { tileSvg } = await import('../../scripts/iconite.mjs');
    assert.throws(() => tileSvg("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><path d='M0 0'/></svg>"), /viewBox/);
    assert.throws(() => tileSvg('nu e un svg'), /viewBox/);
  });
});

describe('aplicatie.html: fără scripturi inline, fără resurse externe, cu clasele din CSS-urile existente', () => {
  test('niciun script inline, niciun handler inline, niciun atribut style', () => {
    for (const match of APP_HTML.matchAll(/<script\b([^>]*)>/gi)) assert.match(match[1], /\bsrc="/, `script fără src: <script${match[1]}>`);
    assert.doesNotMatch(APP_HTML, /\son[a-z]+\s*=/i, 'handler inline');
    assert.doesNotMatch(APP_HTML, /\sstyle\s*=/i, 'atribut style');
  });

  test('src și href sunt doar relative, ancore sau data: (nicio resursă externă)', () => {
    for (const [, reference] of APP_HTML.matchAll(/\b(?:src|href)="([^"]+)"/g)) {
      assert.ok(reference.startsWith('#') || reference.startsWith('data:') || !/^(?:[a-z]+:)?\/\//i.test(reference), `resursă externă: ${reference}`);
    }
  });

  test('politica de conținut din pagină nu relaxează pe cea din Manifest V3 (script-src doar \'self\', fără unsafe-*)', () => {
    const policy = /http-equiv="Content-Security-Policy" content="([^"]+)"/.exec(APP_HTML)[1];
    assert.match(policy, /script-src 'self'(?:;|$)/);
    assert.doesNotMatch(policy, /unsafe-|wasm-unsafe-eval|https?:/);
    assert.match(policy, /connect-src 'none'/);
  });

  test('fiecare clasă folosită în pagină există ca selector în app.css sau dashboard.css (designul e lege)', () => {
    const css = ['app.css', 'dashboard.css'].map((name) => readFileSync(path.join(PROJECT_ROOT, 'interfata', 'assets', name), 'utf8')).join('\n');
    const extra = existsSync(path.join(EXTENSION_DIR, 'src', 'extensie.css')) ? readFileSync(path.join(EXTENSION_DIR, 'src', 'extensie.css'), 'utf8') : '';
    const known = new Set([...(css + extra).matchAll(/\.([A-Za-z_][\w-]*)/g)].map((match) => match[1]));
    const used = new Set();
    for (const [, value] of APP_HTML.matchAll(/\bclass="([^"]+)"/g)) for (const name of value.split(/\s+/).filter(Boolean)) used.add(name);
    const missing = [...used].filter((name) => !known.has(name));
    assert.deepEqual(missing, [], `clase fără regulă în CSS: ${missing.join(', ')}`);
  });

  test('foile de stil sunt exact designul partajat (dashboard.css, app.css) și extensie.css, în ordinea în care se suprascriu', () => {
    const sheets = [...APP_HTML.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((match) => match[1]);
    assert.deepEqual(sheets, ['partajat/dashboard.css', 'partajat/app.css', 'extensie.css']);
  });

  test('scripturile pe care le cere pagina sunt exact cele din build: cele șase din partajat/ și modulul ecranelor', () => {
    const scripts = [...APP_HTML.matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)].map((match) => match[1]);
    assert.deepEqual(scripts, [
      'partajat/app-theme.js', 'partajat/dashboard.js', 'partajat/app-dom.js', 'partajat/app-format.js', 'partajat/app-threshold.js', 'partajat/demo-data.js', 'ecrane/main.js',
    ]);
    assert.match(APP_HTML, /<script type="module" src="ecrane\/main\.js">/);
  });
});

describe('build: dist/ și arhiva', () => {
  let result;
  let out;
  before(() => {
    out = path.join(tempDir('build-extensie'), 'dist');
    result = build({ outDir: out });
  });

  test('conține manifestul (identic cu sursa), worker-ul, pagina, iconițele, LICENSE și configurările generate', () => {
    assert.equal(sha256(path.join(out, 'manifest.json')), sha256(path.join(EXTENSION_DIR, 'manifest.json')));
    for (const name of ['background.js', 'aplicatie.html', 'settings.js', 'LICENSE', 'generat/config.js', 'generat/raport_sursa.js', 'ecrane/main.js', 'colectare/work_tab.js', 'stocare/run_lock.js']) {
      assert.ok(existsSync(path.join(out, name)), `lipsește ${name}`);
    }
    for (const size of [16, 32, 48, 128]) assert.ok(existsSync(path.join(out, 'iconite', `icon-${size}.png`)));
  });

  test('sursele unice se copiază neschimbate în partajat/ (E7)', () => {
    const shared = ['dashboard.js', 'dashboard.css', 'app.css', 'app-theme.js', 'app-dom.js', 'app-format.js', 'app-threshold.js', 'demo-data.js'];
    assert.deepEqual(readdirSync(path.join(out, 'partajat')).sort(), [...shared].sort());
    for (const name of shared) assert.equal(sha256(path.join(out, 'partajat', name)), sha256(path.join(PROJECT_ROOT, 'interfata', 'assets', name)), name);
  });

  test('generat/config.js: exact cele patru configurări publice, egale cu config/*.json, fără regulile personale', async () => {
    const { default: config } = await import(pathToFileURL(path.join(out, 'generat', 'config.js')).href);
    assert.deepEqual(Object.keys(config), ['categorii', 'avertismente', 'culori', 'restituiri']);
    const fromFile = (name) => JSON.parse(readFileSync(path.join(PROJECT_ROOT, 'config', name), 'utf8').replace(BOM_AT_START, ''));
    assert.deepEqual(config.categorii, fromFile('categorii.json'));
    assert.deepEqual(config.avertismente, fromFile('avertismente.json'));
    assert.deepEqual(config.culori, fromFile('culori.json'));
    assert.deepEqual(config.restituiri, fromFile('restituiri.json'));
    assert.ok(!existsSync(path.join(out, 'generat', 'categorii.personal.json')));
  });

  test('generat/raport_sursa.js: șablonul și designul raportului, ca să-l poată lipi buildReport', async () => {
    const { default: report } = await import(pathToFileURL(path.join(out, 'generat', 'raport_sursa.js')).href);
    assert.deepEqual(Object.keys(report), ['appName', 'template', 'css', 'js']);
    assert.equal(report.appName, MANIFEST.name, 'numele exportului vine din manifest');
    assert.equal(report.template, readFileSync(path.join(PROJECT_ROOT, 'templates', 'raport.html'), 'utf8'));
    assert.equal(report.css, readFileSync(path.join(PROJECT_ROOT, 'interfata', 'assets', 'dashboard.css'), 'utf8'));
    assert.equal(report.js, readFileSync(path.join(PROJECT_ROOT, 'interfata', 'assets', 'dashboard.js'), 'utf8'));
    for (const placeholder of ['/*__DASHBOARD_CSS__*/', '/*__DASHBOARD_JS__*/', '/*__DATE_ANALIZA__*/null']) assert.equal(report.template.split(placeholder).length - 1, 1, placeholder);
  });

  test('nimic care nu e extensie nu ajunge în dist/: teste, pachete de dezvoltare, probe', () => {
    const files = listFiles(out);
    for (const name of files) {
      assert.doesNotMatch(name, /(?:^|\/)(?:tests|node_modules|proba|build|scripts)\//, name);
      assert.doesNotMatch(name, /\.test\.js$|package(?:-lock)?\.json$|\.map$/, name);
    }
  });

  test('rezultatul spune versiunea, arhiva și fișierele; arhiva are numele din versiune', () => {
    assert.equal(result.version, MANIFEST.version);
    assert.equal(path.basename(result.zipPath), `cheltuieli-emag-${MANIFEST.version}.zip`);
    assert.ok(existsSync(result.zipPath));
    assert.deepEqual(result.files, listFiles(out, (name) => name === path.basename(result.zipPath)));
  });

  test('arhiva: Python o deschide și o verifică, are manifest.json în rădăcină și exact fișierele din dist/, cu aceleași octeți', () => {
    const script = [
      'import hashlib, json, sys, zipfile',
      'archive = zipfile.ZipFile(sys.argv[1])',
      'assert archive.testzip() is None',
      'print(json.dumps({name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}))',
    ].join('\n');
    const listed = JSON.parse(execFileSync(PYTHON, ['-I', '-c', script, result.zipPath], { encoding: 'utf8' }));
    const expected = Object.fromEntries(result.files.map((name) => [name, sha256(path.join(out, name))]));
    assert.deepEqual(Object.keys(listed).sort(), Object.keys(expected).sort());
    assert.deepEqual(listed, expected);
    assert.ok('manifest.json' in listed);
    for (const name of Object.keys(listed)) assert.ok(!name.startsWith('/') && !name.includes('..') && !name.includes('\\'), name);
  });

  test('structura ZIP: antetul de sfârșit, directorul central și antetele locale se potrivesc între ele (un cititor strict nu se plânge)', () => {
    const zip = readFileSync(result.zipPath);
    const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
    assert.ok(end >= 0, 'lipsește antetul de sfârșit');
    const entriesOnDisk = zip.readUInt16LE(end + 8);
    const entriesTotal = zip.readUInt16LE(end + 10);
    const centralSize = zip.readUInt32LE(end + 12);
    const centralOffset = zip.readUInt32LE(end + 16);
    assert.equal(entriesOnDisk, result.files.length);
    assert.equal(entriesTotal, result.files.length);
    assert.equal(centralOffset + centralSize, end, 'directorul central se termină exact unde începe antetul de sfârșit');
    let cursor = centralOffset;
    for (const name of result.files) {
      assert.equal(zip.readUInt32LE(cursor), 0x02014b50, `antet central lipsă pentru ${name}`);
      const method = zip.readUInt16LE(cursor + 10);
      const crc = zip.readUInt32LE(cursor + 16);
      const compressed = zip.readUInt32LE(cursor + 20);
      const uncompressed = zip.readUInt32LE(cursor + 24);
      const nameLength = zip.readUInt16LE(cursor + 28);
      const localOffset = zip.readUInt32LE(cursor + 42);
      assert.equal(zip.subarray(cursor + 46, cursor + 46 + nameLength).toString('utf8'), name);
      assert.equal(zip.readUInt32LE(localOffset), 0x04034b50, `antet local lipsă pentru ${name}`);
      assert.equal(zip.readUInt16LE(localOffset + 8), method, `${name}: metoda diferă`);
      assert.equal(zip.readUInt32LE(localOffset + 14), crc, `${name}: CRC diferit`);
      assert.equal(zip.readUInt32LE(localOffset + 18), compressed, `${name}: dimensiunea comprimată diferă`);
      assert.equal(zip.readUInt32LE(localOffset + 22), uncompressed, `${name}: dimensiunea necomprimată diferă`);
      assert.equal(uncompressed, readFileSync(path.join(out, name)).length, `${name}: dimensiunea nu e a fișierului`);
      assert.equal(zip.subarray(localOffset + 30, localOffset + 30 + nameLength).toString('utf8'), name);
      cursor += 46 + nameLength;
    }
    assert.equal(cursor, end);
  });

  test('`python -m zipfile -t` trece (comanda din planul de lucru)', () => {
    const output = execFileSync(PYTHON, ['-I', '-m', 'zipfile', '-t', result.zipPath], { encoding: 'utf8' });
    assert.match(output, /Done testing/);
  });

  test('construit de două ori, arhiva are aceiași octeți (nu depinde de ora construirii)', () => {
    const second = build({ outDir: path.join(tempDir('build-extensie-2'), 'dist') });
    assert.equal(sha256(second.zipPath), sha256(result.zipPath));
  });
});

describe('build: verificările opresc o extensie stricată', () => {
  /** O copie a extensiei într-un folder temporar, pe care testul o strică, cu proiectul real alături pentru sursele unice. */
  function brokenCopy(change) {
    const root = tempDir('extensie-stricata');
    cpSync(path.join(EXTENSION_DIR, 'src'), path.join(root, 'src'), { recursive: true });
    cpSync(path.join(EXTENSION_DIR, 'manifest.json'), path.join(root, 'manifest.json'));
    change(root);
    return root;
  }
  const buildCopy = (root, options = {}) => build({ outDir: path.join(tempDir('iesire'), 'dist'), extensionDir: root, ...options });

  test('un fișier cerut de manifest care lipsește oprește build-ul, cu numele lui', () => {
    const root = brokenCopy((dir) => {
      const manifest = { ...MANIFEST, background: { ...MANIFEST.background, service_worker: 'nu_exista.js' } };
      writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(manifest));
    });
    assert.throws(() => buildCopy(root), /nu_exista\.js/);
  });

  test('o iconiță care lipsește oprește build-ul', () => {
    const root = brokenCopy((dir) => rmSync(path.join(dir, 'src', 'iconite', 'icon-48.png')));
    assert.throws(() => buildCopy(root), /icon-48\.png/);
  });

  test('un script cerut de pagină care lipsește oprește build-ul', () => {
    const root = brokenCopy((dir) => {
      const html = readFileSync(path.join(dir, 'src', 'aplicatie.html'), 'utf8').replace('src="ecrane/main.js"', 'src="ecrane/lipsa.js"');
      writeFileSync(path.join(dir, 'src', 'aplicatie.html'), html);
    });
    assert.throws(() => buildCopy(root), /ecrane\/lipsa\.js/);
  });

  test('o resursă externă în pagină oprește build-ul', () => {
    const root = brokenCopy((dir) => {
      const html = readFileSync(path.join(dir, 'src', 'aplicatie.html'), 'utf8').replace('partajat/app.css', 'https://exemplu.invalid/app.css');
      writeFileSync(path.join(dir, 'src', 'aplicatie.html'), html);
    });
    assert.throws(() => buildCopy(root), /resursă externă/);
  });

  test('un import static fără țintă oprește build-ul', () => {
    const root = brokenCopy((dir) => {
      const file = path.join(dir, 'src', 'background.js');
      writeFileSync(file, `import './lipsa.js';\n${readFileSync(file, 'utf8')}`);
    });
    assert.throws(() => buildCopy(root), /lipsa\.js/);
  });

  test('un import ne-relativ (nu se rezolvă în browser) oprește build-ul', () => {
    const root = brokenCopy((dir) => {
      const file = path.join(dir, 'src', 'background.js');
      writeFileSync(file, `import 'playwright-core';\n${readFileSync(file, 'utf8')}`);
    });
    assert.throws(() => buildCopy(root), /nu e relativ/);
  });

  test('un import dinamic fără țintă dă avertisment, iar cu strict oprește build-ul (modulele încărcate leneș)', () => {
    const root = brokenCopy((dir) => {
      const file = path.join(dir, 'src', 'background.js');
      writeFileSync(file, `${readFileSync(file, 'utf8')}\nexport const lazy = () => import('./calcul/inexistent.js');\n`);
    });
    const loose = buildCopy(root);
    assert.ok(loose.warnings.some((warning) => warning.includes('calcul/inexistent.js')));
    assert.throws(() => buildCopy(root, { strict: true }), /calcul\/inexistent\.js/);
  });

  test('o sursă unică lipsă (interfata/assets/...) oprește build-ul cu calea ei', () => {
    const root = brokenCopy(() => {});
    const project = tempDir('proiect-fara-surse');
    mkdirSync(path.join(project, 'interfata', 'assets'), { recursive: true });
    writeFileSync(path.join(project, 'LICENSE'), 'licență de probă');
    assert.throws(() => buildCopy(root, { projectRoot: project }), /lipsește sursa unică/);
  });
});

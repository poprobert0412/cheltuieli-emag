// iconite.mjs — generează iconițele extensiei (16, 32, 48 și 128 px): bonul aplicației (favicon-ul din interfata/aplicatie.html, același desen, nu unul redesenat) pe un pătrat deschis cu colțuri rotunjite.
// Pătratul („varianta B”, aprobată de Robert pe 14.10.2026) e acolo ca bonul, închis la culoare, să se vadă și pe barele întunecate ale browserului; nimic din desenul bonului nu se schimbă, doar se așază pe pătrat.
// Primește: nimic (canalul de browser din EXT_TEST_CHANNEL: implicit „msedge” pe Windows, „chromium” în rest). Dă înapoi: extensie/src/iconite/icon-<mărime>.png, PNG cu transparență; PNG-urile se comit, scriptul nu rulează în CI.
// La 128 px pătratul are 96 px, cu 16 px transparenți pe fiecare parte, cum cere magazinul Chrome (imaginea de 128 px are zonă liberă în jur); la 16, 32 și 48 pătratul umple toată imaginea.
// Browserul pornește fără rețea (--host-resolver-rules=MAP * ~NOTFOUND) și primește desenul ca text: nimic nu se încarcă de nicăieri.
// Ce NU face: nu redesenează bonul și nu schimbă favicon-ul aplicației (pătratul e doar al iconițelor extensiei).
import { chromium } from 'playwright-core';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const EXTENSION_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const APP_HTML = path.join(EXTENSION_DIR, '..', 'interfata', 'aplicatie.html');
export const ICON_DIR = path.join(EXTENSION_DIR, 'src', 'iconite');
export const ICON_SIZES = Object.freeze([16, 32, 48, 128]);
// Mărimea desenului în iconița de 128 px: 96 px, cu 16 px liberi pe fiecare parte (regula magazinului pentru icoana de 128).
const LARGE_ICON_SIZE = 128;
const LARGE_ICON_GLYPH = 96;
const FAVICON_LINK = /<link rel="icon" href="(data:image\/svg\+xml,[^"]+)"/;
// Pătratul de sub bon, în unitățile viewBox-ului favicon-ului (32 x 32). Culoarea e „hârtia”: aproape alb, cu o nuanță caldă, cu contrast mare față de corpul închis al bonului (#14181c);
// raza dă colțuri de ~22% din latură; marginea de 4 unități (12,5% pe fiecare parte) lasă bonul să respire, iar la 16 px rămâne vizibil.
const VIEWBOX_SIZE = 32;
const TILE_FILL = '#f2f3f0';
const TILE_RADIUS = 7;
const TILE_PADDING = 4;
const FAVICON_VIEWBOX = /viewBox=["']0 0 32 32["']/;

/** SVG-ul bonului, exact cum e în favicon-ul paginii aplicației (adresa data: se decodează, nu se redesenează). */
export function receiptSvg() {
  const match = FAVICON_LINK.exec(readFileSync(APP_HTML, 'utf8'));
  if (!match) throw new Error(`nu găsesc favicon-ul (link rel="icon", data:image/svg+xml) în ${APP_HTML}`);
  return decodeURIComponent(match[1].slice(match[1].indexOf(',') + 1));
}

/**
 * Iconița: bonul din `svg` (favicon-ul aplicației) micșorat la 75% și așezat în mijlocul unui pătrat deschis cu colțuri rotunjite, în același viewBox de 32 x 32.
 * Aruncă dacă `svg` nu e un element svg întreg cu viewBox-ul 0 0 32 32 (altfel bonul ar ieși strâmb pe pătrat, fără nicio eroare).
 */
export function tileSvg(svg) {
  const open = svg.indexOf('>') + 1;
  const close = svg.lastIndexOf('</svg>');
  if (!svg.startsWith('<svg') || close < open || !FAVICON_VIEWBOX.test(svg.slice(0, open))) {
    throw new Error('favicon-ul aplicației nu mai e un svg cu viewBox-ul 0 0 32 32: ajustează iconite.mjs înainte să regenerezi iconițele');
  }
  const scale = (VIEWBOX_SIZE - 2 * TILE_PADDING) / VIEWBOX_SIZE;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}">`
    + `<rect width="${VIEWBOX_SIZE}" height="${VIEWBOX_SIZE}" rx="${TILE_RADIUS}" fill="${TILE_FILL}"/>`
    + `<g transform="translate(${TILE_PADDING} ${TILE_PADDING}) scale(${scale})">${svg.slice(open, close)}</g></svg>`;
}

/** Pagina minimală care așază desenul `glyph` px în mijlocul unui pătrat transparent de `size` px. */
function pageFor(svg, size, glyph) {
  const sized = svg.replace('<svg ', `<svg width="${glyph}" height="${glyph}" `);
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:transparent}body{width:${size}px;height:${size}px;display:grid;place-items:center}svg{display:block}</style></head><body>${sized}</body></html>`;
}

/** Randează iconița de `size` px (cu desenul de `glyph` px în mijloc) într-un PNG transparent. */
async function renderIcon(browser, svg, size, glyph) {
  const context = await browser.newContext({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  try {
    const page = await context.newPage();
    await page.setContent(pageFor(svg, size, glyph));
    return await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
  } finally {
    await context.close();
  }
}

/** Generează toate iconițele în ICON_DIR; întoarce numele fișierelor scrise. */
export async function generateIcons() {
  const channel = process.env.EXT_TEST_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium');
  const svg = tileSvg(receiptSvg());
  mkdirSync(ICON_DIR, { recursive: true });
  const browser = await chromium.launch({ channel, args: ['--host-resolver-rules=MAP * ~NOTFOUND'] });
  const written = [];
  try {
    for (const size of ICON_SIZES) {
      const glyph = size === LARGE_ICON_SIZE ? LARGE_ICON_GLYPH : size;
      const png = await renderIcon(browser, svg, size, glyph);
      const name = `icon-${size}.png`;
      writeFileSync(path.join(ICON_DIR, name), png);
      written.push(name);
    }
  } finally {
    await browser.close();
  }
  return written;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  generateIcons().then((names) => console.log(`iconițe scrise în ${ICON_DIR}: ${names.join(', ')}`)).catch((error) => {
    console.error(`eroare: ${error && error.message ? error.message : error}`);
    process.exitCode = 1;
  });
}

// Cardul anonim se desenează o singură dată: aceeași pânză este previzualizarea și PNG-ul.
import { formatLei } from '../calcul/money_ro.js';
import { REVOKE_DELAY_MS } from '../exporturi/descarcare.js';

// Dimensiunile cardului aprobat, la densitate 2× pentru un PNG lizibil.
export const RECAP_SIZE = Object.freeze({ width: 440, height: 374, scale: 2 });

/** Selectează doar datele agregate permise pentru distribuire. */
export function recapData(summary, year, hideSum, demo) {
  const row = summary.by_year.find((item) => String(item.year) === String(year));
  if (!row) throw new Error('Anul ales nu există în analiză.');
  return { year: String(row.year), spent: hideSum ? null : formatLei(row.spent_bani), orders: String(row.orders), units: String(row.kept_units), demo: Boolean(demo) };
}

/** Desenează cardul folosind tokenii reali de temă și fonturile locale ale aplicației. */
export function drawRecap(canvas, data, theme) {
  const { width, height, scale } = RECAP_SIZE;
  canvas.width = width * scale; canvas.height = height * scale;
  const c = canvas.getContext('2d'); if (!c) throw new Error('Previzualizarea imaginii nu este disponibilă.');
  c.scale(scale, scale); c.textBaseline = 'alphabetic';
  c.fillStyle = theme.paper; c.beginPath(); c.roundRect(0.5, 0.5, width - 1, height - 1, 7); c.fill(); c.strokeStyle = theme.rule; c.lineWidth = 1; c.stroke();
  c.fillStyle = theme.ink; c.font = `11px ${theme.sans}`;
  c.fillText('BILANȚUL MEU', 27, 39); c.textAlign = 'right'; c.fillText(data.demo ? 'EMAG · DEMO' : 'EMAG', width - 27, 39); c.textAlign = 'left';
  c.font = `700 47px ${theme.display}`; c.fillText(data.year, 27, 112); const yearWidth = c.measureText(data.year).width; c.fillStyle = theme.hl; c.fillText('.', 27 + yearWidth, 112);
  if (data.spent !== null) {
    c.fillStyle = theme.ink3; c.font = `13px ${theme.sans}`; c.fillText('Plătit efectiv', 27, 146);
    c.fillStyle = theme.ink; const amount = data.spent.replace(/ Lei$/, '');
    let fontSize = 32; c.font = `700 ${fontSize}px ${theme.mono}`;
    while (c.measureText(`${amount} Lei`).width > width - 54 && fontSize > 16) { fontSize -= 1; c.font = `700 ${fontSize}px ${theme.mono}`; }
    c.fillText(amount, 27, 180); const offset = c.measureText(amount).width; c.font = `500 15px ${theme.mono}`; c.fillText(' Lei', 27 + offset, 180);
  }
  c.strokeStyle = theme.rule2; c.setLineDash([3, 2]);
  for (const y of [207, 295]) { c.beginPath(); c.moveTo(27, y); c.lineTo(width - 27, y); c.stroke(); } c.setLineDash([]);
  c.fillStyle = theme.ink; c.font = `700 26px ${theme.mono}`; c.fillText(data.orders, 27, 248); c.fillText(data.units, 227, 248);
  c.fillStyle = theme.ink3; c.font = `13px ${theme.sans}`; c.fillText('comenzi înregistrate', 27, 274); c.fillText('produse păstrate', 227, 274);
  c.font = `10px ${theme.sans}`; c.fillText('Cât am cheltuit pe eMAG · creat de Robert Pop', 27, 329);
  if (data.demo) c.fillText('Exemplu cu date inventate', 27, 345);
}

/** Salvează exact pânza vizibilă, fără alte date sau cereri de rețea. */
export async function downloadRecap(canvas, year, active = () => true) {
  // toBlob și toDataURL rotunjesc diferit RGB-ul unor pixeli semitransparenți.
  // Folosim aceeași serializare PNG ca previzualizarea verificată, fără recodare.
  const base64 = canvas.toDataURL('image/png').split(',')[1];
  if (!base64) throw new Error('Imaginea nu a putut fi creată.');
  const blob = new Blob([Uint8Array.from(atob(base64), (character) => character.charCodeAt(0))], { type: 'image/png' });
  if (!active()) return;
  const url = URL.createObjectURL(blob); const a = document.createElement('a');
  a.href = url; a.download = `bilant-${year}.png`; a.hidden = true; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}

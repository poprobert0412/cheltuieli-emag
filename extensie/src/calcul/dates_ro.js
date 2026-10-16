// Citirea datelor scrise românește de eMAG („26 mai 2026, 10:07”), portul lui emag_spend/dates_ro.py.
// Primește: text cu o dată. Dă înapoi: ISO „2026-05-26T10:07” sau null. Lunile se recunosc după primele 3 litere (fără diacritice),
// deci merg și formele scurte din liste („ian”, „noi”) și cele întregi din detalii („ianuarie”, „noiembrie”). Ziua, ora și minutul nu se validează (ca în Python).
// Ce NU face: nu verifică dacă ziua există în lună și nu citește ore fără minute.
import { cpSlice, pyInt } from './python_compat.js';
import { PyPattern } from './python_regex.js';
import { normalizeText } from './text_normalize.js';

const MONTHS = new Map([
  ['ian', 1], ['feb', 2], ['mar', 3], ['apr', 4], ['mai', 5], ['iun', 6],
  ['iul', 7], ['aug', 8], ['sep', 9], ['oct', 10], ['noi', 11], ['dec', 12],
]);
// Literele românești din numele lunii, atât cu virgulă (ș ț, forma corectă), cât și cu sedilă (paginile le amestecă); scrise din coduri, fiindcă literele cu sedilă nu au voie în surse.
const ROMANIAN_LETTERS = String.fromCodePoint(0x103, 0xe2, 0xee, 0x219, 0x21b, 0x15f, 0x163, 0x102, 0xc2, 0xce, 0x218, 0x21a);
const DATE_RE = new PyPattern(String.raw`(\d{1,2})\s+([A-Za-z${ROMANIAN_LETTERS}]+)\.?\s+(\d{4})(?:,?\s+(\d{1,2}):(\d{2}))?`);

/** Număr cu zerouri în față până la `width` caractere (an pe 4, restul pe 2), ca {:04d} și {:02d} din Python. */
function pad(value, width) {
  return String(value).padStart(width, '0');
}

/** Întoarce data ca ISO „YYYY-MM-DDTHH:MM” (ora 00:00 dacă lipsește), sau null dacă textul nu are o dată cu lună recunoscută. */
export function parseRoDatetime(text) {
  const match = DATE_RE.search(text || '');
  if (!match) return null;
  const [day, monthName, year, hour, minute] = match.groups();
  const month = MONTHS.get(cpSlice(normalizeText(monthName), 0, 3));
  if (month === undefined) return null;
  const hours = hour === null ? 0 : pyInt(hour);
  const minutes = minute === null ? 0 : pyInt(minute);
  return `${pad(pyInt(year), 4)}-${pad(month, 2)}-${pad(pyInt(day), 2)}T${pad(hours, 2)}:${pad(minutes, 2)}`;
}

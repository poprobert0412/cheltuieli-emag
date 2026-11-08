// Calendarul campaniei: ore locale RO și instanțe explicite, fără dependență de fusul calculatorului.
// Limitele locale inexistente/ambigue la DST sunt refuzate; comenzile fără oră precisă rămân neatribuite.
export const SHOPPING_TIME_ZONE = 'Europe/Bucharest';
const DAY_MS = 24 * 60 * 60 * 1000; // Sonde înainte/după zi găsesc ambele offseturi ale unei schimbări DST.
const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: SHOPPING_TIME_ZONE, year: 'numeric', month: '2-digit',
  day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
const TIMESTAMP = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::([0-5]\d)(?:\.(\d{1,3}))?)?(Z|[+-]\d{2}:\d{2})?$/;

/** Zi ISO calendaristică reală, fără normalizarea zilelor inexistente. */
export function isShoppingDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

/** Ora de 24 de ore, exact HH:MM; 24:00 se exprimă prin 00:00 în ziua următoare. */
export function isShoppingTime(value) { return typeof value === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value); }

/** Instanta formatată ca oră locală RO; folosită și pentru validarea round-trip a offseturilor DST. */
function localStamp(milliseconds) {
  const parts = Object.fromEntries(formatter.formatToParts(new Date(milliseconds)).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return `${parts.year.padStart(4, '0')}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

/** Instanțele compatibile cu o oră locală: zero la gap DST, două la fold DST, exact una pentru o oră precisă. */
function localInstants(stamp) {
  const nominal = Date.parse(`${stamp}Z`);
  const offsets = new Set([-DAY_MS, 0, DAY_MS].map((delta) => {
    const probe = nominal + delta;
    return Date.parse(`${localStamp(probe)}Z`) - probe;
  }));
  return [...offsets].map((offset) => nominal - offset).filter((instant) => localStamp(instant) === stamp);
}

/** Verifică intervalul [start,end); null/null este starea explicită de migrare care cere orele utilizatorului. */
export function validateCampaign(campaign) {
  if (!campaign || !isShoppingDate(campaign.from) || !isShoppingDate(campaign.to) || campaign.from > campaign.to) throw new TypeError('campanie: interval invalid (data calendaristică).');
  if (campaign.time_zone !== SHOPPING_TIME_ZONE) throw new TypeError('Fusul perioadei trebuie să fie Europe/Bucharest.');
  if (campaign.start_time === null && campaign.end_time === null) return { start_ms: null, end_ms: null, time_required: true };
  if (!isShoppingTime(campaign.start_time) || !isShoppingTime(campaign.end_time)) throw new TypeError('Completează ambele ore în format HH:MM.');
  const boundary = (day, time) => {
    const values = localInstants(`${day}T${time}:00`);
    if (values.length === 0) throw new TypeError('Ora aleasă este inexistentă la schimbarea orei de vară.');
    if (values.length > 1) throw new TypeError('Ora aleasă este ambiguă la schimbarea orei de vară.');
    return values[0];
  };
  const start = boundary(campaign.from, campaign.start_time); const end = boundary(campaign.to, campaign.end_time);
  if (end <= start) throw new TypeError('Sfârșitul trebuie să fie după început.');
  return { start_ms: start, end_ms: end, time_required: false };
}

/** Instanță precisă a comenzii, ori null când ziua/ora/offsetul lipsește sau este invalid/ambiguu. */
export function orderTimestamp(value) {
  if (typeof value !== 'string') return null;
  const match = TIMESTAMP.exec(value);
  if (!match || !isShoppingDate(match[1]) || !isShoppingTime(match[2])) return null;
  const [, day, time, second = '00', fraction = '', zone] = match;
  if (zone) {
    if (zone !== 'Z' && !/^[+-](?:[01]\d|2[0-3]):[0-5]\d$/.test(zone)) return null;
    const instant = Date.parse(`${day}T${time}:${second}${fraction ? `.${fraction}` : ''}${zone}`);
    return Number.isFinite(instant) ? instant : null;
  }
  const values = localInstants(`${day}T${time}:${second}`);
  return values.length === 1 ? values[0] + Number(fraction.padEnd(3, '0')) : null;
}

/** Ziua locală RO a unui timestamp precis, ori ziua brută a unei comenzi fără oră. */
export function orderLocalDate(value) {
  const instant = orderTimestamp(value);
  if (instant !== null) return localStamp(instant).slice(0, 10);
  return typeof value === 'string' && isShoppingDate(value.slice(0, 10)) ? value.slice(0, 10) : null;
}

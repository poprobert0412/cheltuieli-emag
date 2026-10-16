// Ecranul „Analiza e în lucru”: cei 4 pași, mesajul mare, bara de progres cu numere și butonul „Oprește” (portul părții de desenare din interfata/assets/app-run.js).
// Primește: instantaneele raportorului de progres (colectare/progress.js: faza, făcute din total, mesajul propriu, oprirea cerută) și clicul pe „Oprește”. Dă înapoi: nimic; cheamă `onCancel`.
// Pașii: 1 Conectare, 2 Comenzi, 3 Retururi, 4 Calcul; cei dinaintea celui activ sunt „gata”. Fără salturi de layout: variantele mesajului stau suprapuse în aceeași celulă (înălțime = a celei mai înalte).
// Cititoare de ecran: schimbările de pas și, din sfert în sfert de progres, cifrele se anunță în zona live (nu la fiecare citire).
// Ce NU face: nu calculează progresul (colectorul îl raportează) și nu schimbă ecranul (login la nevoie: main.js).
import {
  PHASE_ANALYZING, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_STARTING, PHASE_WAITING_LOGIN,
} from '../colectare/progress.js';

const STEP_KEYS = ['login', 'orders', 'returns', 'calc'];
const STEP_NAMES = ['Conectare', 'Comenzi', 'Retururi', 'Calcul'];
// Pasul activ pentru fiecare fază (cât se așteaptă login-ul, pasul „Conectare” rămâne activ).
const ACTIVE_STEP = Object.freeze({
  [PHASE_STARTING]: 0, [PHASE_WAITING_LOGIN]: 0, [PHASE_FETCHING_ORDERS]: 1, [PHASE_FETCHING_RETURNS]: 2, [PHASE_ANALYZING]: 3,
});
const STATUS_TEXT = Object.freeze({ pending: 'în așteptare', active: 'în lucru', done: 'gata' });
const NOUNS = Object.freeze({ [PHASE_FETCHING_ORDERS]: 'Comenzi', [PHASE_FETCHING_RETURNS]: 'Retururi' });
// Cifrele de progres se anunță cititoarelor de ecran din 25 în 25 la sută, nu la fiecare citire (ar vorbi încontinuu).
const ANNOUNCE_EVERY_PERCENT = 25;
const FULL_PERCENT = 100;
// Ce se arată lângă bara de progres după „Oprește”, până se închide fila de lucru (ca CANCELLING_MESSAGE din app_runner.py).
const CANCELLING_MESSAGE = 'Opresc analiza… se termină în câteva secunde, apoi se închide și fila eMAG de lucru.';

let lastStep = -1;
let lastBucket = -1;

/** Pune starea fiecărui pas în listă: marcajul, textul de stare și aria-current pe cel activ. */
function renderSteps(activeIndex) {
  STEP_KEYS.forEach((key, index) => {
    const item = document.querySelector(`#steps [data-step="${key}"]`);
    if (!item) return;
    let status = 'pending';
    if (index < activeIndex) status = 'done';
    else if (index === activeIndex) status = 'active';
    item.setAttribute('data-status', status);
    if (status === 'active') item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
    item.querySelector('.step__status').textContent = STATUS_TEXT[status];
  });
}

/** Mesajul mare: se vede varianta fazei curente (login-ul are ecranul lui, deci acolo se arată „Pornesc”). */
function renderCallout(phase) {
  const key = phase === PHASE_WAITING_LOGIN ? PHASE_STARTING : phase;
  window.App.dom.byId('work-callout').setAttribute('data-kind', 'info');
  for (const item of document.querySelectorAll('#work-callout .callout__item')) {
    if (item.getAttribute('data-state') === key) item.setAttribute('data-active', '');
    else item.removeAttribute('data-active');
  }
}

/** Bara și eticheta ei: cu total cunoscut „Comenzi: 325 din 416”, fără total „citite până acum”, la calcul indeterminată. */
function renderProgress(snapshot) {
  const { dom, format } = window.App;
  const box = dom.byId('progress');
  const bar = dom.byId('progress-bar');
  const fill = dom.byId('progress-fill');
  const label = dom.byId('progress-label');
  const noun = NOUNS[snapshot.phase];
  let mode = 'idle';
  let text = 'Pornesc…';
  let percent = -1;
  if (noun && snapshot.total !== null && snapshot.total > 0) {
    const done = Math.min(Math.max(snapshot.done, 0), snapshot.total);
    percent = Math.round((done / snapshot.total) * FULL_PERCENT);
    mode = 'determinate';
    text = `${noun}: ${format.count(done)} din ${format.count(snapshot.total)}`;
  } else if (noun) {
    mode = 'indeterminate';
    text = snapshot.done > 0 ? `${noun}: ${format.count(snapshot.done)} citite până acum` : `${noun}: încep…`;
  } else if (snapshot.phase === PHASE_ANALYZING) {
    mode = 'indeterminate';
    text = 'Calculez raportul…';
  }
  box.setAttribute('data-mode', mode);
  label.textContent = text;
  if (mode === 'determinate') {
    bar.setAttribute('aria-valuenow', String(percent));
    bar.setAttribute('aria-valuetext', text);
    fill.style.transform = `scaleX(${percent / FULL_PERCENT})`;
  } else {
    bar.removeAttribute('aria-valuenow');
    bar.removeAttribute('aria-valuetext');
    fill.style.transform = '';
  }
  return { percent, text, mode, counted: Boolean(noun) };
}

/** Anunță schimbarea de pas și, din sfert în sfert, progresul. */
function announceChanges(activeIndex, progressInfo) {
  const { dom } = window.App;
  if (activeIndex !== lastStep && lastStep !== -1) dom.announce(`Pasul ${activeIndex + 1} din ${STEP_NAMES.length}: ${STEP_NAMES[activeIndex]}.`);
  if (progressInfo.percent >= 0) {
    const bucket = Math.floor(progressInfo.percent / ANNOUNCE_EVERY_PERCENT);
    if (bucket !== lastBucket && lastBucket !== -1 && activeIndex === lastStep) dom.announce(progressInfo.text);
    lastBucket = bucket;
  } else {
    lastBucket = -1;
  }
  lastStep = activeIndex;
}

/** La intrarea pe ecran: uită ce s-a anunțat la rularea de dinainte și readuce butonul „Oprește” la starea de început. */
export function enterWorking() {
  lastStep = -1;
  lastBucket = -1;
  const button = window.App.dom.byId('btn-cancel');
  button.textContent = 'Oprește';
  button.removeAttribute('aria-disabled');
  button.removeAttribute('aria-busy');
}

/** Desenează tot ecranul din instantaneul `snapshot` al raportorului de progres. */
export function renderWorking(snapshot) {
  const activeIndex = ACTIVE_STEP[snapshot.phase] ?? 0;
  renderSteps(activeIndex);
  renderCallout(snapshot.phase);
  const progressInfo = renderProgress(snapshot);
  // Mesajul propriu se arată doar unde spune ceva în plus: la căutarea paginilor din listă („pagina 3 din 12”, fără total) și după „Oprește”. În rest repetă titlul de mai sus sau cifrele din bară.
  const detailAdds = (progressInfo.counted && progressInfo.mode === 'indeterminate') || snapshot.cancelRequested;
  let detail = '';
  if (snapshot.cancelRequested) detail = CANCELLING_MESSAGE;
  else if (detailAdds && snapshot.message) detail = snapshot.message;
  window.App.dom.byId('work-detail').textContent = detail;
  announceChanges(activeIndex, progressInfo);
}

/** Leagă butonul „Oprește”: cere oprirea și rămâne pe loc, dar nu mai cere încă o dată. */
export function initWorkingScreen({ onCancel }) {
  const { dom } = window.App;
  dom.byId('btn-cancel').addEventListener('click', (event) => {
    const button = event.currentTarget;
    if (button.getAttribute('aria-disabled') === 'true') return;
    button.textContent = 'Se oprește…';
    button.setAttribute('aria-disabled', 'true');
    button.setAttribute('aria-busy', 'true');
    dom.announce('Opresc analiza…');
    onCancel();
  });
}

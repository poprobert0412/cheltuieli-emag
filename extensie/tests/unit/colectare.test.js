// Teste unitare pentru extensie/src/colectare/: citirea contului eMAG, pe o filă falsă (fără browser) și pe un chrome fals.
// Fila falsă imită doar ce folosește codul (navigate, runInTab, sleep, now), ca testele din tests/test_scrapers_with_fakes.py pentru programul Python:
// paginarea, dublurile, schelete apoi listă stabilă, reîncercările, sesiunea expirată, „Vezi mai mult”, oprirea cerută de om.
// Timpul e fals (FakeClock): o pauză de 25 de secunde durează o milisecundă, deci testele nu așteaptă nimic. Funcțiile injectate în pagină
// (page_functions.js) se probează în browser, nu aici: fila falsă răspunde după identitatea funcției cerute.
// Ce NU face: nu atinge rețeaua și nu pornește Chrome; verificarea în Edge cu extensia încărcată e un pas separat.
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  BASE_URL, FETCH_BACKOFF_SECONDS, FETCH_CONCURRENCY, FETCH_RETRIES, LIST_RENDER_TIMEOUT_SECONDS, LOGIN_POLL_SECONDS, LOGIN_WAIT_SECONDS,
  MAX_RETURN_LOAD_MORE_CLICKS,
} from '../../src/settings.js';
import { PageChanged, collectAll } from '../../src/colectare/emag_collector.js';
import { collectOrderIds } from '../../src/colectare/order_list_scraper.js';
import { FetchFailed, SessionExpired, fetchEach } from '../../src/colectare/page_fetcher.js';
import {
  pageClickLoadMore, pageFetch, pageHasReturnLinks, pageLastPageHint, pageLoadMoreState, pageLoginState, pageOrderIds, pageReturnPaths,
} from '../../src/colectare/page_functions.js';
import {
  NO_LOG, PHASE_ANALYZING, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_STARTING, PHASE_WAITING_LOGIN, Progress, RunCancelled,
} from '../../src/colectare/progress.js';
import { collectReturnPaths } from '../../src/colectare/return_list_scraper.js';
import {
  CODE_BUSY, CODE_LOGIN_TIMEOUT, CODE_NETWORK, CODE_PAGE_CHANGED, CODE_SESSION_EXPIRED, CODE_STORAGE_FULL, CODE_UNEXPECTED, CODE_WORK_TAB_CLOSED, ERROR_CODES,
  classifyError,
} from '../../src/colectare/run_errors.js';
import { LoginTimeout, ensureLoggedIn, isLoginAddress, isOutsideAccount } from '../../src/colectare/session_check.js';
import {
  NavigationFailed, PageNotAccessible, WorkTabClosed, closeTab, navigate, openWorkTab, runInTab, showTab,
} from '../../src/colectare/work_tab.js';

// ---------- unelte de test ----------

const PLACEHOLDER = '0'.repeat(9);
const LOGIN_URL = `${BASE_URL}/user/login?ref=history`;
const TAB_ID = 7;

/** Ceas fals: pauzele nu așteaptă, doar înaintează timpul și se notează. */
class FakeClock {
  /** Pornește la o oră fixă, fără nicio pauză făcută. */
  constructor() {
    this.t = 1_000_000;
    this.sleeps = [];
  }

  /** Ora falsă curentă în milisecunde. */
  now() {
    return this.t;
  }

  /** O pauză fără așteptare: o notează și înaintează ceasul. */
  async sleep(ms) {
    this.sleeps.push(ms);
    this.t += ms;
    await Promise.resolve();
  }
}

/** Jurnal care reține rândurile (nivel, modul, text) ca testele să le poată căuta. */
class RecordingLog {
  /** Începe fără niciun rând. */
  constructor() {
    this.lines = [];
  }

  /** Rând de nivel INFO. */
  info(module, text) {
    this.lines.push(['INFO', module, text]);
  }

  /** Rând de nivel WARNING. */
  warning(module, text) {
    this.lines.push(['WARNING', module, text]);
  }

  /** Rând de nivel ERROR. */
  error(module, text) {
    this.lines.push(['ERROR', module, text]);
  }

  /** True dacă există un rând de nivelul dat care conține fragmentul. */
  has(level, fragment) {
    return this.lines.some(([lineLevel, , text]) => lineLevel === level && text.includes(fragment));
  }
}

/** Numărul paginii dintr-o adresă de listă de comenzi (1 pentru prima pagină, fără număr în cale). */
function pageNumberOf(url) {
  const match = /\/history\/shopping\/(\d+)/.exec(url);
  return match ? Number(match[1]) : 1;
}

/**
 * Site fals: ține pagina curentă și răspunde funcțiilor injectate. `ordersByPage`: număr de pagină -> lista de numere (stabilă) sau { reads: [citiri succesive] };
 * `details`: cale -> răspuns sau listă de răspunsuri succesive (ultimul se repetă); `returnBatches`: loturile dezvăluite de „Vezi mai mult”.
 */
class FakeSite {
  /** Opțiunile descriu site-ul: paginile de comenzi, detaliile, loturile de retururi, redirecturile și când devine „logat”; fără ele, un site gol, logat. */
  constructor(options = {}) {
    this.clock = new FakeClock();
    this.ordersByPage = options.ordersByPage ?? {};
    this.lastPage = options.lastPage ?? 1;
    this.details = options.details ?? {};
    this.returnBatches = options.returnBatches ?? [];
    this.growOnClick = options.growOnClick ?? true;
    this.redirects = options.redirects ?? {};
    this.loginAfterChecks = options.loginAfterChecks ?? 0;
    this.loginChecks = 0;
    this.pageFailsUntil = options.pageFailsUntil ?? 0;
    this.onRun = options.onRun ?? null;
    this.visited = [];
    this.opened = [];
    this.closed = [];
    this.shown = [];
    this.calls = [];
    this.fetched = [];
    this.inFlight = 0;
    this.maxInFlight = 0;
    this.currentUrl = '';
    this.reads = new Map();
    this.shownBatches = 1;
    this.clicks = 0;
    this.scriptedFetch = new Map();
  }

  /** Obiectul `io` pe care îl primesc scraperele: fila falsă, ceasul fals și notarea apelurilor. */
  io() {
    return {
      openWorkTab: async (options) => {
        this.opened.push(options ?? null);
        return TAB_ID;
      },
      navigate: async (tabId, url) => {
        assert.equal(tabId, TAB_ID);
        this.visited.push(url);
        this.currentUrl = this.redirects[url] ?? url;
        this.reads.delete(this.currentUrl);
        return this.currentUrl;
      },
      runInTab: async (tabId, func, args = []) => this.run(tabId, func, args),
      showTab: async (tabId) => {
        this.shown.push(tabId);
      },
      closeTab: async (tabId) => {
        this.closed.push(tabId);
      },
      sleep: (ms) => this.clock.sleep(ms),
      now: () => this.clock.now(),
    };
  }

  /** Numărul paginii de listă pe care e fila acum. */
  get page() {
    return pageNumberOf(this.currentUrl);
  }

  /** Răspunde unei funcții injectate după identitatea ei, ca pagina adevărată. */
  async run(tabId, func, args) {
    assert.equal(tabId, TAB_ID);
    this.calls.push(func.name);
    if (this.onRun) this.onRun(func.name, this);
    switch (func) {
      case pageLoginState: {
        this.loginChecks += 1;
        return { logat: this.loginChecks > this.loginAfterChecks, adresa_de_login: isLoginAddress(this.currentUrl) };
      }
      case pageOrderIds: {
        const entry = this.ordersByPage[this.page];
        if (entry === undefined) return [];
        if (Array.isArray(entry)) return [...entry];
        let queue = this.reads.get(this.currentUrl);
        if (!queue) {
          queue = [...entry.reads];
          this.reads.set(this.currentUrl, queue);
        }
        return [...(queue.length > 1 ? queue.shift() : queue[0])];
      }
      case pageLastPageHint:
        return this.lastPage;
      case pageHasReturnLinks:
        return this.returnBatches.length > 0;
      case pageReturnPaths:
        return this.returnBatches.slice(0, this.shownBatches).flat();
      case pageLoadMoreState: {
        const more = this.shownBatches < this.returnBatches.length;
        return { exista: more, vizibil: more };
      }
      case pageClickLoadMore: {
        this.clicks += 1;
        if (this.growOnClick) this.shownBatches += 1;
        return true;
      }
      case pageFetch:
        return this.fetch(args[0]);
      default:
        throw new Error(`funcție necunoscută în fila falsă: ${func.name}`);
    }
  }

  /** Răspunsul fals la o cerere de detalii; ține și evidența cererilor aflate în zbor deodată. */
  async fetch(path) {
    this.fetched.push(path);
    this.inFlight += 1;
    this.maxInFlight = Math.max(this.maxInFlight, this.inFlight);
    await new Promise((resolve) => setImmediate(resolve));
    this.inFlight -= 1;
    let script = this.details[path];
    if (script === undefined) script = { status: 200, html: `<html>${path}</html>` };
    const list = Array.isArray(script) ? script : [script];
    const index = this.scriptedFetch.get(path) ?? 0;
    this.scriptedFetch.set(path, index + 1);
    const outcome = list[Math.min(index, list.length - 1)];
    if (outcome.throws) throw outcome.throws;
    if (outcome.eroare) return { eroare: outcome.eroare };
    return { status: outcome.status ?? 200, finalUrl: outcome.finalUrl ?? BASE_URL + path, html: outcome.html ?? `<html>${path}</html>` };
  }
}

/** Progres real care notează fiecare schimbare ca instantaneu (copie). */
function recordingProgress() {
  const snapshots = [];
  const progress = new Progress({ onChange: (snapshot) => snapshots.push(snapshot) });
  return { progress, snapshots };
}

// ---------- progres ----------

describe('Progress: faza, contorul, mesajul și oprirea cerută', () => {
  test('începe în faza „starting”, fără contor și fără mesaj', () => {
    const { progress } = recordingProgress();
    assert.deepEqual(progress.snapshot(), { phase: PHASE_STARTING, done: 0, total: null, message: '', cancelRequested: false });
  });

  test('o fază nouă pornește contorul de la 0 și șterge mesajul propriu (ca _set_phase din app_runner)', () => {
    const { progress } = recordingProgress();
    progress.phase(PHASE_FETCHING_ORDERS);
    progress.advance(5, 20);
    progress.message('Caut comenzile în cont: pagina 2');
    assert.deepEqual(progress.snapshot(), { phase: PHASE_FETCHING_ORDERS, done: 5, total: 20, message: 'Caut comenzile în cont: pagina 2', cancelRequested: false });
    progress.phase(PHASE_FETCHING_RETURNS, 3);
    assert.deepEqual(progress.snapshot(), { phase: PHASE_FETCHING_RETURNS, done: 0, total: 3, message: '', cancelRequested: false });
  });

  test('o fază necunoscută se ignoră, ca în Python', () => {
    const { progress } = recordingProgress();
    progress.phase(PHASE_FETCHING_ORDERS);
    progress.phase('nu_exista');
    assert.equal(progress.snapshot().phase, PHASE_FETCHING_ORDERS);
  });

  test('fiecare schimbare anunță ascultătorul cu un instantaneu nou', () => {
    const { progress, snapshots } = recordingProgress();
    progress.phase(PHASE_WAITING_LOGIN);
    progress.message('Loghează-te');
    progress.advance(1, 2);
    assert.equal(snapshots.length, 3);
    assert.equal(snapshots[0].phase, PHASE_WAITING_LOGIN);
    assert.equal(snapshots[1].message, 'Loghează-te');
    assert.equal(snapshots[2].done, 1);
    snapshots[2].done = 99;
    assert.equal(progress.snapshot().done, 1, 'instantaneul e o copie');
  });

  test('cancel() se vede în instantaneu, iar raiseIfCancelled() aruncă RunCancelled doar după el', () => {
    const { progress } = recordingProgress();
    progress.raiseIfCancelled();
    progress.cancel();
    assert.equal(progress.snapshot().cancelRequested, true);
    assert.throws(() => progress.raiseIfCancelled(), RunCancelled);
  });

  test('după încheiere, apelurile târzii nu mai schimbă nimic (lucrători rămași în urmă)', () => {
    const { progress, snapshots } = recordingProgress();
    progress.phase(PHASE_ANALYZING);
    progress.finish();
    const before = snapshots.length;
    progress.advance(3, 4);
    progress.message('târziu');
    assert.equal(snapshots.length, before);
  });

  test('NO_LOG nu scrie nimic și nu aruncă', () => {
    NO_LOG.info('x', 'a');
    NO_LOG.warning('x', 'a');
    NO_LOG.error('x', 'a');
  });
});

// ---------- verificarea login-ului ----------

describe('isLoginAddress și isOutsideAccount', () => {
  test('recunoaște „login” în adresă, fără să conteze literele mari', () => {
    assert.equal(isLoginAddress(`${BASE_URL}/user/login?ref=x`), true);
    assert.equal(isLoginAddress('https://auth.emag.ro/User/LOGIN'), true);
    assert.equal(isLoginAddress(`${BASE_URL}/history/shopping?time=older`), false);
  });

  test('adresa goală (fila a ajuns pe o gazdă fără permisiune) înseamnă „în afara contului”', () => {
    assert.equal(isOutsideAccount(''), true);
    assert.equal(isOutsideAccount(LOGIN_URL), true);
    assert.equal(isOutsideAccount(`${BASE_URL}/history/shopping?time=older`), false);
  });
});

describe('ensureLoggedIn: sesiunea activă, login așteptat, termen depășit, oprire', () => {
  const listUrl = `${BASE_URL}/history/shopping?time=older`;

  test('sesiune activă: nu schimbă faza, nu cheamă onNeedLogin și deschide lista o singură dată', async () => {
    const site = new FakeSite();
    const { progress, snapshots } = recordingProgress();
    const log = new RecordingLog();
    let needed = 0;
    await ensureLoggedIn(TAB_ID, progress, { onNeedLogin: () => { needed += 1; }, log }, site.io());
    assert.deepEqual(site.visited, [listUrl]);
    assert.equal(needed, 0);
    assert.equal(snapshots.length, 0);
    assert.ok(log.has('INFO', 'sesiune eMAG activă'));
  });

  test('nelogat: trece în faza de login, cheamă onNeedLogin o dată, verifică la LOGIN_POLL_SECONDS și redeschide lista la final', async () => {
    const site = new FakeSite({ loginAfterChecks: 3 }); // verificarea 1 (după navigare), 2 și 3 (interogări) dau „nelogat”; a 4-a „logat”
    const { progress, snapshots } = recordingProgress();
    const log = new RecordingLog();
    let needed = 0;
    await ensureLoggedIn(TAB_ID, progress, { onNeedLogin: () => { needed += 1; }, log }, site.io());
    assert.equal(needed, 1);
    assert.equal(snapshots[0].phase, PHASE_WAITING_LOGIN);
    assert.match(snapshots[1].message, /Loghează-te în fila eMAG/);
    assert.match(snapshots[1].message, /10 minute/);
    assert.deepEqual(site.clock.sleeps, [LOGIN_POLL_SECONDS * 1000, LOGIN_POLL_SECONDS * 1000, LOGIN_POLL_SECONDS * 1000]);
    assert.deepEqual(site.visited, [listUrl, listUrl], 'lista se redeschide după login, ca în Python');
    assert.ok(log.has('INFO', 'login reușit'));
  });

  test('redirect spre login: nu se citește pagina de login, se așteaptă direct', async () => {
    const site = new FakeSite({ redirects: { [listUrl]: LOGIN_URL }, loginAfterChecks: 0 });
    const { progress } = recordingProgress();
    await ensureLoggedIn(TAB_ID, progress, { log: new RecordingLog() }, site.io());
    assert.equal(site.loginChecks, 1, 'o singură verificare: cea din interogare; pagina de login nu se citește după navigare');
    assert.equal(progress.snapshot().phase, PHASE_WAITING_LOGIN);
  });

  test('gazdă fără permisiune (adresă goală): așteaptă; PageNotAccessible din pagină nu oprește așteptarea', async () => {
    const site = new FakeSite();
    const io = site.io();
    let polls = 0;
    io.navigate = async (tabId, url) => {
      site.visited.push(url);
      site.currentUrl = polls < 3 ? '' : url;
      return site.currentUrl;
    };
    io.runInTab = async (tabId, func) => {
      assert.equal(func, pageLoginState);
      polls += 1;
      if (polls < 3) throw new PageNotAccessible('Cannot access contents of the page');
      return { logat: true, adresa_de_login: false };
    };
    const { progress } = recordingProgress();
    await ensureLoggedIn(TAB_ID, progress, { log: new RecordingLog() }, io);
    assert.equal(polls, 3);
  });

  test('termenul LOGIN_WAIT_SECONDS depășit: LoginTimeout, după exact atâtea interogări cât încap', async () => {
    const site = new FakeSite({ loginAfterChecks: Infinity });
    const { progress } = recordingProgress();
    await assert.rejects(ensureLoggedIn(TAB_ID, progress, { log: new RecordingLog() }, site.io()), LoginTimeout);
    assert.equal(site.clock.sleeps.length, LOGIN_WAIT_SECONDS / LOGIN_POLL_SECONDS);
  });

  test('oprirea cerută cât așteaptă login-ul: RunCancelled la următoarea interogare, după cel mult o pauză', async () => {
    const { progress } = recordingProgress();
    const site = new FakeSite({ loginAfterChecks: Infinity, onRun: () => { if (site.loginChecks === 1) progress.cancel(); } });
    await assert.rejects(ensureLoggedIn(TAB_ID, progress, { log: new RecordingLog() }, site.io()), RunCancelled);
    assert.equal(site.clock.sleeps.length, 2, 'cererea vine în prima interogare; a doua pauză se termină și abia atunci se vede oprirea');
  });

  test('fila de lucru închisă cât se așteaptă: WorkTabClosed trece mai departe', async () => {
    const site = new FakeSite({ loginAfterChecks: Infinity });
    const io = site.io();
    let calls = 0;
    const original = io.runInTab;
    io.runInTab = async (...args) => {
      calls += 1;
      if (calls === 3) throw new WorkTabClosed();
      return original(...args);
    };
    const { progress } = recordingProgress();
    await assert.rejects(ensureLoggedIn(TAB_ID, progress, { log: new RecordingLog() }, io), WorkTabClosed);
  });
});

// ---------- lista de comenzi ----------

describe('collectOrderIds: paginarea, dublurile, schelete și listă stabilă', () => {
  const pagesVisited = (site) => site.visited.map(pageNumberOf);

  test('parcurge fiecare pagină, în ordine, și păstrează ordinea din listă', async () => {
    const site = new FakeSite({ ordersByPage: { 1: ['10', '9'], 2: ['8', '7'], 3: ['6'] }, lastPage: 3 });
    const { progress } = recordingProgress();
    const ids = await collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io());
    assert.deepEqual(ids, ['10', '9', '8', '7', '6']);
    assert.deepEqual(pagesVisited(site), [1, 2, 3]);
  });

  test('mesajele de progres spun pagina și totalul cunoscut', async () => {
    const site = new FakeSite({ ordersByPage: { 1: ['3'], 2: ['2'], 3: ['1'] }, lastPage: 3 });
    const { progress, snapshots } = recordingProgress();
    await collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io());
    assert.deepEqual(snapshots.map((s) => s.message), ['Caut comenzile în cont: pagina 2 din 3', 'Caut comenzile în cont: pagina 3 din 3']);
  });

  test('elimină dublurile când paginile s-au deplasat (o comandă nouă a apărut între cereri)', async () => {
    const site = new FakeSite({ ordersByPage: { 1: ['10', '9', '8'], 2: ['8', '7', '6'] }, lastPage: 2 });
    const { progress } = recordingProgress();
    assert.deepEqual(await collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), ['10', '9', '8', '7', '6']);
  });

  test('ignoră scheletele 000000000: o pagină cu doar schelete e goală și prima pagină goală e eroare', async () => {
    const site = new FakeSite({ ordersByPage: { 1: [PLACEHOLDER, PLACEHOLDER, PLACEHOLDER] } });
    const { progress } = recordingProgress();
    await assert.rejects(collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), /nicio comandă pe prima pagină/);
  });

  test('citirea e stabilă abia la a doua citire identică, fără schelete (listă randată de JavaScript)', async () => {
    const site = new FakeSite({
      ordersByPage: { 1: { reads: [[PLACEHOLDER, PLACEHOLDER, PLACEHOLDER], ['111', PLACEHOLDER], ['111', '222'], ['111', '222']] } },
      lastPage: 1,
    });
    const { progress } = recordingProgress();
    const log = new RecordingLog();
    const ids = await collectOrderIds(TAB_ID, 2, progress, log, site.io());
    assert.deepEqual(ids, ['111', '222']);
    assert.deepEqual(site.clock.sleeps, [700, 700, 700]);
  });

  test('paginare necunoscută: sondează o pagină în plus, goală, o singură dată, și se oprește', async () => {
    const site = new FakeSite({ ordersByPage: { 1: ['3', '2'], 2: ['1'] }, lastPage: 1 });
    const { progress } = recordingProgress();
    assert.deepEqual(await collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), ['3', '2', '1']);
    assert.deepEqual(pagesVisited(site), [1, 2, 3]);
  });

  test('o pagină din mijloc care rămâne goală oprește citirea cu un mesaj care o numește', async () => {
    const site = new FakeSite({ ordersByPage: { 1: ['5', '4'], 3: ['1'] }, lastPage: 3 });
    const { progress } = recordingProgress();
    await assert.rejects(collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), /pagina 2 din 3/);
    assert.deepEqual(pagesVisited(site), [1, 2, 2], 'a doua încercare pe aceeași pagină, ca în Python');
  });

  test('respectă limita de comenzi', async () => {
    const site = new FakeSite({ ordersByPage: { 1: ['10', '9'], 2: ['8', '7'], 3: ['6'] }, lastPage: 3 });
    const { progress } = recordingProgress();
    assert.deepEqual(await collectOrderIds(TAB_ID, 3, progress, new RecordingLog(), site.io()), ['10', '9', '8']);
    assert.deepEqual(pagesVisited(site), [1, 2], 'nu mai cere pagini după ce are destule');
  });

  test('redirect spre login la o pagină din mijloc: SessionExpired, nu „pagină goală”', async () => {
    const page3 = `${BASE_URL}/history/shopping/3?time=older`;
    const site = new FakeSite({ ordersByPage: { 1: ['9'], 2: ['8'], 3: ['7'] }, lastPage: 3, redirects: { [page3]: LOGIN_URL } });
    const { progress } = recordingProgress();
    await assert.rejects(collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), SessionExpired);
  });

  test('gazdă fără permisiune la o pagină din listă: tot SessionExpired', async () => {
    const page2 = `${BASE_URL}/history/shopping/2?time=older`;
    const site = new FakeSite({ ordersByPage: { 1: ['9'], 2: ['8'] }, lastPage: 2, redirects: { [page2]: '' } });
    const { progress } = recordingProgress();
    await assert.rejects(collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), SessionExpired);
  });

  test('oprirea cerută între pagini: RunCancelled și nicio pagină în plus', async () => {
    const { progress } = recordingProgress();
    const site = new FakeSite({
      ordersByPage: { 1: ['9'], 2: ['8'], 3: ['7'] },
      lastPage: 3,
      onRun: (name, self) => { if (name === 'pageOrderIds' && self.page === 2) progress.cancel(); },
    });
    await assert.rejects(collectOrderIds(TAB_ID, null, progress, new RecordingLog(), site.io()), RunCancelled);
    assert.deepEqual(pagesVisited(site), [1, 2]);
  });

  test('timpul de randare: o listă care nu se stabilizează se întoarce cu ce s-a citit, după LIST_RENDER_TIMEOUT_SECONDS', async () => {
    let counter = 0;
    const site = new FakeSite({ lastPage: 1 });
    site.ordersByPage = { 1: { reads: [] } };
    const io = site.io();
    const original = io.runInTab;
    io.runInTab = async (tabId, func, args) => (func === pageOrderIds ? [`${1000 + (counter += 1)}`] : original(tabId, func, args)); // mereu alte numere: niciodată două citiri egale
    const { progress } = recordingProgress();
    const started = site.clock.now();
    const ids = await collectOrderIds(TAB_ID, 1, progress, new RecordingLog(), io);
    assert.equal(ids.length, 1);
    assert.ok(site.clock.now() - started >= LIST_RENDER_TIMEOUT_SECONDS * 1000);
  });
});

// ---------- lista de retururi ----------

describe('collectReturnPaths: „Vezi mai mult”, cont fără retururi, sesiune expirată', () => {
  const returnPath = (n) => `/user/return-history/1/${n}`;
  const batch = (from, to) => Array.from({ length: to - from }, (_, i) => returnPath(from + i));

  test('apasă „Vezi mai mult” până se arată toate loturile', async () => {
    const site = new FakeSite({ returnBatches: [batch(0, 10), batch(10, 12)] });
    const { progress } = recordingProgress();
    const paths = await collectReturnPaths(TAB_ID, progress, new RecordingLog(), site.io());
    assert.equal(paths.length, 12);
    assert.equal(site.clicks, 1);
  });

  test('mesajul de progres spune câte retururi s-au găsit până acum', async () => {
    const site = new FakeSite({ returnBatches: [batch(0, 10), batch(10, 12)] });
    const { progress, snapshots } = recordingProgress();
    await collectReturnPaths(TAB_ID, progress, new RecordingLog(), site.io());
    assert.deepEqual(snapshots.map((s) => s.message), ['Caut retururile în cont: 10 găsite până acum', 'Caut retururile în cont: 12 găsite până acum']);
  });

  test('butonul nu mai adaugă nimic: se oprește după pauza de creștere (15 secunde), fără bucle', async () => {
    const site = new FakeSite({ returnBatches: [batch(0, 10), batch(10, 12)], growOnClick: false });
    const { progress } = recordingProgress();
    const started = site.clock.now();
    const paths = await collectReturnPaths(TAB_ID, progress, new RecordingLog(), site.io());
    assert.equal(paths.length, 10);
    assert.equal(site.clicks, 1);
    assert.ok(site.clock.now() - started >= 15_000);
  });

  test('cont fără retururi: listă goală și un avertisment în jurnal (nu eroare)', async () => {
    const site = new FakeSite({ returnBatches: [] });
    const { progress } = recordingProgress();
    const log = new RecordingLog();
    assert.deepEqual(await collectReturnPaths(TAB_ID, progress, log, site.io()), []);
    assert.ok(log.has('WARNING', 'niciun retur'));
    assert.ok(site.clock.now() - 1_000_000 >= LIST_RENDER_TIMEOUT_SECONDS * 1000);
  });

  test('redirect spre login la lista de retururi: SessionExpired, nu „zero retururi” (altfel produsele returnate ar conta ca păstrate)', async () => {
    const url = `${BASE_URL}/user/return-history`;
    const site = new FakeSite({ returnBatches: [], redirects: { [url]: LOGIN_URL } });
    const { progress } = recordingProgress();
    await assert.rejects(collectReturnPaths(TAB_ID, progress, new RecordingLog(), site.io()), SessionExpired);
  });

  test('plafonul MAX_RETURN_LOAD_MORE_CLICKS oprește o listă care crește la nesfârșit', async () => {
    const batches = Array.from({ length: MAX_RETURN_LOAD_MORE_CLICKS + 20 }, (_, i) => batch(i * 2, i * 2 + 2));
    const site = new FakeSite({ returnBatches: batches });
    const { progress } = recordingProgress();
    await collectReturnPaths(TAB_ID, progress, new RecordingLog(), site.io());
    assert.equal(site.clicks, MAX_RETURN_LOAD_MORE_CLICKS);
  });

  test('oprirea cerută între apăsări: RunCancelled', async () => {
    const { progress } = recordingProgress();
    const site = new FakeSite({
      returnBatches: [batch(0, 2), batch(2, 4), batch(4, 6)],
      onRun: (name, self) => { if (name === 'pageClickLoadMore' && self.clicks === 1) progress.cancel(); },
    });
    await assert.rejects(collectReturnPaths(TAB_ID, progress, new RecordingLog(), site.io()), RunCancelled);
  });
});

// ---------- descărcarea paginilor de detalii ----------

describe('fetchEach: ordinea, reîncercările, sesiunea expirată, concurența, oprirea', () => {
  const handler = (path, html) => `${path}:${html}`;

  test('păstrează ordinea căilor și aplică handler-ul pe fiecare (ca test_fetch_each_keeps_path_order din Python)', async () => {
    const site = new FakeSite({ details: { '/p/1': { html: 'A' }, '/p/2': { html: 'A' }, '/p/3': { html: 'A' } } });
    const { progress } = recordingProgress();
    const out = await fetchEach(TAB_ID, ['/p/1', '/p/2', '/p/3'], handler, 'test', progress, new RecordingLog(), site.io());
    assert.deepEqual(out, ['/p/1:A', '/p/2:A', '/p/3:A']);
  });

  test('rezultatele rămân în ordinea căilor chiar dacă una se termină mai târziu', async () => {
    const site = new FakeSite();
    const io = site.io();
    const original = io.runInTab;
    io.runInTab = async (tabId, func, args) => {
      if (func === pageFetch && args[0] === '/p/1') await new Promise((resolve) => setTimeout(resolve, 15));
      return original(tabId, func, args);
    };
    const { progress } = recordingProgress();
    const out = await fetchEach(TAB_ID, ['/p/1', '/p/2', '/p/3'], handler, 'test', progress, new RecordingLog(), io);
    assert.deepEqual(out, ['/p/1:<html>/p/1</html>', '/p/2:<html>/p/2</html>', '/p/3:<html>/p/3</html>']);
  });

  test('reîncearcă după o eroare trecătoare, cu pauza FETCH_BACKOFF_SECONDS × încercarea', async () => {
    const site = new FakeSite({ details: { '/p/1': [{ eroare: 'timeout' }, { html: 'ok' }] } });
    const { progress } = recordingProgress();
    const log = new RecordingLog();
    const out = await fetchEach(TAB_ID, ['/p/1'], (p, h) => h, 'test', progress, log, site.io());
    assert.deepEqual(out, ['ok']);
    assert.equal(site.fetched.length, 2);
    assert.deepEqual(site.clock.sleeps, [FETCH_BACKOFF_SECONDS * 1000]);
    assert.ok(log.has('WARNING', '/p/1: încercarea 1/3 a eșuat (timeout)'));
  });

  test('renunță după FETCH_RETRIES încercări, cu mesajul „nu am putut descărca” și fără pauză după ultima', async () => {
    const site = new FakeSite({ details: { '/p/1': { status: 500 } } });
    const { progress } = recordingProgress();
    await assert.rejects(fetchEach(TAB_ID, ['/p/1'], (p, h) => h, 'test', progress, new RecordingLog(), site.io()), (error) => {
      assert.ok(error instanceof FetchFailed);
      assert.match(error.message, /nu am putut descărca \/p\/1: HTTP 500/);
      return true;
    });
    assert.equal(site.fetched.length, FETCH_RETRIES);
    assert.deepEqual(site.clock.sleeps, [2000, 4000]);
  });

  test('redirect spre login: SessionExpired, fără reîncercări inutile', async () => {
    const site = new FakeSite({ details: { '/p/1': { status: 200, finalUrl: 'https://auth.emag.ro/user/login', html: '' } } });
    const { progress } = recordingProgress();
    await assert.rejects(fetchEach(TAB_ID, ['/p/1'], (p, h) => h, 'test', progress, new RecordingLog(), site.io()), SessionExpired);
    assert.equal(site.fetched.length, 1);
  });

  test('o cale care conține „login” nu e tratată ca sesiune expirată', async () => {
    const site = new FakeSite({ details: { '/user/login-info': { status: 200, finalUrl: `${BASE_URL}/user/login-info`, html: 'pagina' } } });
    const { progress } = recordingProgress();
    const out = await fetchEach(TAB_ID, ['/user/login-info'], (p, h) => h, 'test', progress, new RecordingLog(), site.io());
    assert.deepEqual(out, ['pagina']);
  });

  test('fila de lucru închisă: WorkTabClosed trece imediat, fără reîncercări', async () => {
    const site = new FakeSite({ details: { '/p/1': { throws: new WorkTabClosed() } } });
    const { progress } = recordingProgress();
    await assert.rejects(fetchEach(TAB_ID, ['/p/1'], (p, h) => h, 'test', progress, new RecordingLog(), site.io()), WorkTabClosed);
    assert.equal(site.fetched.length, 1);
  });

  test('pagina inaccesibilă (utilizatorul a mutat fila) se reîncearcă, apoi eșuează cu ultimul motiv', async () => {
    const site = new FakeSite({ details: { '/p/1': { throws: new PageNotAccessible('Cannot access contents of the page') } } });
    const { progress } = recordingProgress();
    await assert.rejects(fetchEach(TAB_ID, ['/p/1'], (p, h) => h, 'test', progress, new RecordingLog(), site.io()), PageNotAccessible);
    assert.equal(site.fetched.length, FETCH_RETRIES);
  });

  test('cere cel mult FETCH_CONCURRENCY pagini deodată și le termină pe toate', async () => {
    const paths = Array.from({ length: 11 }, (_, i) => `/p/${i}`);
    const site = new FakeSite();
    const { progress } = recordingProgress();
    const out = await fetchEach(TAB_ID, paths, handler, 'test', progress, new RecordingLog(), site.io());
    assert.equal(out.length, 11);
    assert.equal(site.maxInFlight, FETCH_CONCURRENCY);
  });

  test('prima eroare oprește cererile noi (cele deja pornite se termină, fără să mai fie procesate) și se aruncă eroarea', async () => {
    const paths = Array.from({ length: 10 }, (_, i) => `/p/${i}`);
    const site = new FakeSite({ details: { '/p/0': { throws: new SessionExpired('expirat') } } });
    const { progress } = recordingProgress();
    const handled = [];
    await assert.rejects(fetchEach(TAB_ID, paths, (path, html) => { handled.push(path); return html; }, 'test', progress, new RecordingLog(), site.io()), SessionExpired);
    assert.ok(!site.fetched.includes('/p/3'), 'nicio cerere nouă după eroare');
    assert.deepEqual(handled, [], 'paginile care se terminau după eroare nu mai ajung la handler');
  });

  test('o eroare din handler (pagină schimbată) oprește totul și ajunge la apelant', async () => {
    const site = new FakeSite();
    const { progress } = recordingProgress();
    await assert.rejects(
      fetchEach(TAB_ID, ['/p/1', '/p/2'], () => { throw new PageChanged('/p/1', 'lipsește «Comanda nr.»'); }, 'test', progress, new RecordingLog(), site.io()),
      PageChanged,
    );
  });

  test('oprirea cerută: RunCancelled, iar handler-ul nu mai rulează după ea', async () => {
    const { progress } = recordingProgress();
    const handled = [];
    const site = new FakeSite();
    const paths = Array.from({ length: 12 }, (_, i) => `/p/${i}`);
    await assert.rejects(fetchEach(TAB_ID, paths, (path) => { handled.push(path); progress.cancel(); return path; }, 'test', progress, new RecordingLog(), site.io()), RunCancelled);
    assert.ok(handled.length <= FETCH_CONCURRENCY, `handler rulat de ${handled.length} ori`);
  });

  test('progresul: 0 din total la început, apoi numărul descărcat; jurnalul scrie din 25 în 25 și la final', async () => {
    const paths = Array.from({ length: 60 }, (_, i) => `/p/${i}`);
    const site = new FakeSite();
    const { progress, snapshots } = recordingProgress();
    const log = new RecordingLog();
    await fetchEach(TAB_ID, paths, handler, 'comenzi', progress, log, site.io());
    assert.deepEqual([snapshots[0].done, snapshots[0].total], [0, 60]);
    assert.deepEqual([snapshots.at(-1).done, snapshots.at(-1).total], [60, 60]);
    const dones = snapshots.map((s) => s.done);
    assert.deepEqual(dones, [...dones].sort((a, b) => a - b), 'contorul nu scade');
    const infoTexts = log.lines.filter(([level]) => level === 'INFO').map(([, , text]) => text);
    assert.deepEqual(infoTexts, ['comenzi: 25/60 descărcate', 'comenzi: 50/60 descărcate', 'comenzi: 60/60 descărcate']);
  });

  test('o listă goală nu cere nimic și întoarce o listă goală', async () => {
    const site = new FakeSite();
    const { progress } = recordingProgress();
    assert.deepEqual(await fetchEach(TAB_ID, [], handler, 'test', progress, new RecordingLog(), site.io()), []);
    assert.equal(site.fetched.length, 0);
  });
});

// ---------- colectorul întreg ----------

describe('collectAll: fluxul întreg pe o filă falsă, cu parsere false', () => {
  const orderPath = (id) => `/history/shoppingdetails/${id}`;
  const parsers = {
    parseOrderPage: (path, html) => ({ order_id: path.split('/').pop(), html }),
    parseReturnPage: (path, html) => ({ return_path: path, html }),
  };
  const returnPath = '/user/return-history/1/55';

  /** Un site complet: două comenzi pe o pagină, un retur; `extra` schimbă oricare opțiune. */
  function fullSite(extra = {}) {
    return new FakeSite({ ordersByPage: { 1: ['302', '301'] }, lastPage: 1, returnBatches: [[returnPath]], ...extra });
  }

  test('citește comenzile, apoi retururile, în fazele din progress.py, și închide fila de lucru', async () => {
    const site = fullSite();
    const { progress, snapshots } = recordingProgress();
    const result = await collectAll({ maxOrders: null, progress, log: new RecordingLog(), parsers, io: site.io() });
    assert.deepEqual(result.orders.map((o) => o.order_id), ['302', '301']);
    assert.deepEqual(result.returns.map((r) => r.return_path), [returnPath]);
    assert.deepEqual(site.fetched.sort(), [orderPath('301'), orderPath('302'), returnPath].sort());
    assert.deepEqual(site.closed, [TAB_ID]);
    const phases = snapshots.map((s) => s.phase).filter((phase, i, all) => i === 0 || phase !== all[i - 1]);
    assert.deepEqual(phases, [PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS]);
  });

  test('anunță fila de lucru prin onWorkTab, înainte de login, și o deschide lângă fila aplicației (openerTabId)', async () => {
    const site = fullSite();
    const { progress } = recordingProgress();
    const order = [];
    const io = site.io();
    const originalNavigate = io.navigate;
    io.navigate = async (...args) => {
      order.push('navigate');
      return originalNavigate(...args);
    };
    await collectAll({ progress, log: new RecordingLog(), parsers, io, openerTabId: 41, onWorkTab: (id) => order.push(`tab:${id}`) });
    assert.deepEqual(site.opened, [{ openerTabId: 41 }]);
    assert.equal(order[0], `tab:${TAB_ID}`);
  });

  test('nelogat: cheamă onNeedLogin, așteaptă login-ul și merge mai departe', async () => {
    const site = fullSite({ loginAfterChecks: 2 });
    const { progress, snapshots } = recordingProgress();
    let needed = 0;
    const result = await collectAll({ progress, log: new RecordingLog(), parsers, io: site.io(), onNeedLogin: () => { needed += 1; } });
    assert.equal(needed, 1);
    assert.equal(result.orders.length, 2);
    assert.ok(snapshots.some((s) => s.phase === PHASE_WAITING_LOGIN));
  });

  test('limita de comenzi ajunge la scraper', async () => {
    const site = fullSite({ ordersByPage: { 1: ['9', '8', '7'] } });
    const { progress } = recordingProgress();
    const result = await collectAll({ maxOrders: 2, progress, log: new RecordingLog(), parsers, io: site.io() });
    assert.deepEqual(result.orders.map((o) => o.order_id), ['9', '8']);
  });

  test('fila de lucru se închide și la eroare, iar eroarea originală nu se pierde', async () => {
    const site = fullSite({ details: { [orderPath('301')]: { status: 200, finalUrl: LOGIN_URL, html: '' } } });
    const io = site.io();
    io.closeTab = async (id) => {
      site.closed.push(id);
      throw new Error('fila nu mai există');
    };
    const { progress } = recordingProgress();
    await assert.rejects(collectAll({ progress, log: new RecordingLog(), parsers, io }), SessionExpired);
    assert.deepEqual(site.closed, [TAB_ID]);
  });

  test('fila de lucru se închide și la oprirea cerută', async () => {
    const { progress } = recordingProgress();
    const site = fullSite({ onRun: (name) => { if (name === 'pageFetch') progress.cancel(); } });
    await assert.rejects(collectAll({ progress, log: new RecordingLog(), parsers, io: site.io() }), RunCancelled);
    assert.deepEqual(site.closed, [TAB_ID]);
  });

  test('un parser care aruncă devine PageChanged, cu calea paginii și motivul parserului', async () => {
    const site = fullSite();
    const { progress } = recordingProgress();
    const failing = { parseOrderPage: () => { throw new Error('lipsește «Comanda nr.»'); }, parseReturnPage: parsers.parseReturnPage };
    await assert.rejects(collectAll({ progress, log: new RecordingLog(), parsers: failing, io: site.io() }), (error) => {
      assert.ok(error instanceof PageChanged);
      assert.match(error.message, /\/history\/shoppingdetails\/30[12]/);
      assert.match(error.message, /lipsește «Comanda nr\.»/);
      return true;
    });
    assert.deepEqual(site.closed, [TAB_ID]);
  });

  test('un cont fără retururi dă o listă goală de retururi, nu eroare', async () => {
    const site = fullSite({ returnBatches: [] });
    const { progress } = recordingProgress();
    const result = await collectAll({ progress, log: new RecordingLog(), parsers, io: site.io() });
    assert.deepEqual(result.returns, []);
  });
});

// ---------- erorile ----------

describe('classifyError: cod stabil și mesaj în română cu „Ce faci”', () => {
  const kinds = [
    [new LoginTimeout('x'), CODE_LOGIN_TIMEOUT],
    [new SessionExpired('x'), CODE_SESSION_EXPIRED],
    [new WorkTabClosed(), CODE_WORK_TAB_CLOSED],
    [new PageNotAccessible('Cannot access'), CODE_WORK_TAB_CLOSED],
    [new PageChanged('/p/1', 'lipsește «Comanda nr.»'), CODE_PAGE_CHANGED],
    [new FetchFailed('nu am putut descărca /p/1: HTTP 500'), CODE_NETWORK],
    [new NavigationFailed('pagina nu s-a încărcat'), CODE_NETWORK],
  ];
  for (const [error, code] of kinds) {
    test(`${error.constructor.name} -> ${code}`, () => {
      const result = classifyError(error);
      assert.equal(result.code, code);
      assert.match(result.message, /Ce faci: /);
      assert.ok(ERROR_CODES.includes(code));
    });
  }

  test('LoginTimeout spune câte minute a așteptat programul', () => {
    assert.match(classifyError(new LoginTimeout('x')).message, new RegExp(`${LOGIN_WAIT_SECONDS / 60} minute`));
  });

  test('erorile cu cod din alte module (lacăt ocupat, stocare plină) se recunosc după cod, fără import', () => {
    const busy = Object.assign(new Error('x'), { code: CODE_BUSY });
    const full = Object.assign(new Error('x'), { code: CODE_STORAGE_FULL });
    assert.equal(classifyError(busy).code, CODE_BUSY);
    assert.equal(classifyError(full).code, CODE_STORAGE_FULL);
    assert.match(classifyError(busy).message, /altă filă/);
    assert.match(classifyError(full).message, /Șterge datele/);
  });

  test('o eroare de cotă a browserului (fără cod) devine „stocare plină”', () => {
    assert.equal(classifyError(new Error('QUOTA_BYTES quota exceeded')).code, CODE_STORAGE_FULL);
  });

  test('o eroare obișnuită arată primul rând al mesajului, tăiat; una de programare doar tipul', () => {
    const plain = classifyError(new Error(`${'a'.repeat(400)}\nal doilea rând`));
    assert.equal(plain.code, CODE_UNEXPECTED);
    assert.ok(plain.message.includes('a'.repeat(300)) && !plain.message.includes('a'.repeat(301)));
    assert.ok(!plain.message.includes('al doilea rând'));
    const programming = classifyError(new TypeError('x.y is not a function'));
    assert.equal(programming.code, CODE_UNEXPECTED);
    assert.match(programming.message, /TypeError/);
    assert.ok(!programming.message.includes('is not a function'));
  });

  test('nu aruncă și nu întoarce un mesaj gol, orice ar primi', () => {
    for (const value of [null, undefined, 'text', 42, {}, new Error(''), Object.assign(new Error('x'), { code: 'necunoscut' })]) {
      const result = classifyError(value);
      assert.ok(ERROR_CODES.includes(result.code));
      assert.ok(result.message.length > 20);
    }
  });

  test('toate codurile au un mesaj propriu, diferit de celelalte', () => {
    const messages = new Set();
    for (const [error] of kinds) messages.add(classifyError(error).message);
    assert.ok(messages.size >= 5);
  });
});

// ---------- fila de lucru (chrome fals) ----------

/** chrome fals cu fila de lucru: evenimente asincrone ca în browser (loading, apoi complete), erori cu mesajele măsurate în Edge 155. */
function makeFakeChrome(options = {}) {
  const updated = new Set();
  const removed = new Set();
  const tabs = new Map();
  let nextId = 100;
  const behavior = {
    finalUrl: undefined, hideUrl: false, loadingEvent: true, staleCompleteFirst: false, neverComplete: false, completeDelay: 1, ...options,
  };
  const scriptingCalls = [];
  const calls = [];

  /** Anunță toți ascultătorii din `set` cu argumentele date. */
  function emit(set, ...args) {
    for (const listener of [...set]) listener(...args);
  }

  /** Imită navigarea lui Chrome: „loading”, apoi „complete” după `completeDelay`, cu variantele cerute de opțiuni. */
  function runNavigation(tab, url) {
    setTimeout(() => {
      if (!tabs.has(tab.id)) return;
      if (behavior.staleCompleteFirst) emit(updated, tab.id, { status: 'complete' }, { ...tab, status: 'complete', url: tab.url });
      if (behavior.loadingEvent) emit(updated, tab.id, { status: 'loading', url }, { ...tab, status: 'loading' });
      setTimeout(() => {
        if (!tabs.has(tab.id) || behavior.neverComplete) return;
        tab.url = behavior.finalUrl ?? url;
        tab.status = 'complete';
        emit(updated, tab.id, { status: 'complete' }, { ...tab, url: behavior.hideUrl ? undefined : tab.url });
      }, behavior.completeDelay);
    }, 0);
  }

  const chrome = {
    tabs: {
      onUpdated: { addListener: (fn) => updated.add(fn), removeListener: (fn) => updated.delete(fn) },
      onRemoved: { addListener: (fn) => removed.add(fn), removeListener: (fn) => removed.delete(fn) },
      async create(props) {
        calls.push(['create', props]);
        const tab = { id: nextId += 1, url: props.url, status: 'loading', active: props.active, windowId: 3 };
        tabs.set(tab.id, tab);
        setTimeout(() => {
          tab.status = 'complete';
          emit(updated, tab.id, { status: 'complete' }, { ...tab });
        }, behavior.completeDelay);
        return { ...tab };
      },
      async update(id, props) {
        calls.push(['update', id, props, updated.size]);
        const tab = tabs.get(id);
        if (!tab) throw new Error(`No tab with id: ${id}.`);
        if (options.updateRejects) throw new Error(options.updateRejects);
        if (props.url !== undefined) {
          tab.status = 'loading';
          runNavigation(tab, props.url);
        }
        if (props.active !== undefined) tab.active = props.active;
        return { ...tab };
      },
      async get(id) {
        const tab = tabs.get(id);
        if (!tab) throw new Error(`No tab with id: ${id}.`);
        return { ...tab };
      },
      async remove(id) {
        calls.push(['remove', id]);
        if (!tabs.has(id)) throw new Error(`No tab with id: ${id}.`);
        tabs.delete(id);
        emit(removed, id, {});
      },
    },
    scripting: {
      async executeScript(injection) {
        scriptingCalls.push(injection);
        if (options.scriptError) throw new Error(options.scriptError);
        if (options.scriptResults) return options.scriptResults;
        return [{ frameId: 0, result: { eco: injection.args } }];
      },
    },
    windows: {
      async update(id, props) {
        calls.push(['windows.update', id, props]);
        return {};
      },
    },
  };
  return { chrome, tabs, updated, removed, calls, scriptingCalls, behavior };
}

/** Rulează `body` cu un chrome fals pus global, apoi îl scoate. */
async function withChrome(options, body) {
  const fake = makeFakeChrome(options);
  const previous = globalThis.chrome;
  globalThis.chrome = fake.chrome;
  try {
    return await body(fake);
  } finally {
    if (previous === undefined) delete globalThis.chrome;
    else globalThis.chrome = previous;
  }
}

describe('work_tab.openWorkTab și closeTab', () => {
  test('creează fila goală, inactivă, lângă fila aplicației, și așteaptă să fie „complete”', async () => {
    await withChrome({}, async (fake) => {
      const tabId = await openWorkTab({ openerTabId: 12 });
      assert.deepEqual(fake.calls[0], ['create', { url: 'about:blank', active: false, openerTabId: 12 }]);
      assert.equal(fake.tabs.get(tabId).status, 'complete');
    });
  });

  test('fără openerTabId (lipsă, null sau ceva care nu e număr întreg) nu trimite cheia: Chrome refuză alte valori', async () => {
    for (const options of [undefined, {}, { openerTabId: null }, { openerTabId: 'x' }]) {
      await withChrome({}, async (fake) => {
        await openWorkTab(options);
        assert.deepEqual(fake.calls[0], ['create', { url: 'about:blank', active: false }]);
      });
    }
  });

  test('closeTab închide fila și ignoră o filă care nu mai există', async () => {
    await withChrome({}, async (fake) => {
      const tabId = await openWorkTab();
      await closeTab(tabId);
      assert.equal(fake.tabs.has(tabId), false);
      await closeTab(tabId);
      await closeTab(99999);
    });
  });

  test('showTab activează fila și aduce fereastra ei în față', async () => {
    await withChrome({}, async (fake) => {
      const tabId = await openWorkTab();
      await showTab(tabId);
      assert.ok(fake.calls.some(([name, id, props]) => name === 'update' && id === tabId && props.active === true));
      assert.ok(fake.calls.some(([name, , props]) => name === 'windows.update' && props.focused === true));
    });
  });
});

describe('work_tab.navigate: ascultătorul înaintea navigării (cursa descrisă la E6)', () => {
  test('ascultătorul de încărcare există deja când Chrome primește tabs.update', async () => {
    await withChrome({}, async (fake) => {
      const tabId = await openWorkTab();
      await navigate(tabId, `${BASE_URL}/x`, 1000);
      const updateCall = fake.calls.find(([name]) => name === 'update');
      assert.equal(updateCall[3], 1, 'un ascultător onUpdated înregistrat în momentul navigării');
    });
  });

  test('întoarce adresa finală din evenimentul „complete” (după redirecturi)', async () => {
    await withChrome({ finalUrl: LOGIN_URL }, async () => {
      const tabId = await openWorkTab();
      assert.equal(await navigate(tabId, `${BASE_URL}/x`, 1000), LOGIN_URL);
    });
  });

  test('adresa lipsă (gazdă fără permisiune) devine un șir gol', async () => {
    await withChrome({ hideUrl: true }, async () => {
      const tabId = await openWorkTab();
      assert.equal(await navigate(tabId, 'https://auth.emag.ro/user/login', 1000), '');
    });
  });

  test('un „complete” vechi, venit înaintea lui „loading”, nu încheie navigarea', async () => {
    await withChrome({ staleCompleteFirst: true, completeDelay: 30 }, async () => {
      const tabId = await openWorkTab();
      const started = Date.now();
      await navigate(tabId, `${BASE_URL}/x`, 2000);
      assert.ok(Date.now() - started >= 25, 'a așteptat „complete” al navigării noi');
    });
  });

  test('evenimentele altor file se ignoră, chiar dacă o altă filă își încheie o încărcare cât navighează aceasta', async () => {
    await withChrome({ completeDelay: 40 }, async (fake) => {
      const tabId = await openWorkTab();
      const promise = navigate(tabId, `${BASE_URL}/x`, 2000);
      const other = { id: tabId + 50, url: 'https://altceva.test/' };
      for (const listener of [...fake.updated]) {
        listener(other.id, { status: 'loading', url: other.url }, other);
        listener(other.id, { status: 'complete' }, other);
      }
      assert.equal(await promise, `${BASE_URL}/x`);
    });
  });

  test('fila închisă în timpul navigării: WorkTabClosed', async () => {
    await withChrome({ completeDelay: 50 }, async (fake) => {
      const tabId = await openWorkTab();
      const promise = navigate(tabId, `${BASE_URL}/x`, 2000);
      setTimeout(() => { fake.tabs.delete(tabId); for (const listener of [...fake.removed]) listener(tabId, {}); }, 10);
      await assert.rejects(promise, WorkTabClosed);
    });
  });

  test('tabs.update respins cu „No tab with id”: WorkTabClosed', async () => {
    await withChrome({}, async () => {
      await assert.rejects(navigate(424242, `${BASE_URL}/x`, 1000), WorkTabClosed);
    });
  });

  test('tabs.update care aruncă pe loc (argumente refuzate): navigate respinge și își scoate ascultătorii', async () => {
    await withChrome({}, async (fake) => {
      const tabId = await openWorkTab();
      fake.chrome.tabs.update = () => { throw new TypeError('argumente greșite'); };
      await assert.rejects(navigate(tabId, `${BASE_URL}/x`, 1000), /argumente greșite/);
      assert.equal(fake.updated.size, 0);
      assert.equal(fake.removed.size, 0);
    });
  });

  test('o navigare care nu se termină: NavigationFailed la termen', async () => {
    await withChrome({ neverComplete: true }, async () => {
      const tabId = await openWorkTab();
      await assert.rejects(navigate(tabId, `${BASE_URL}/x`, 40), NavigationFailed);
    });
  });

  test('după încheiere, ascultătorii se scot (nu se strâng la sute de pagini)', async () => {
    await withChrome({}, async (fake) => {
      const tabId = await openWorkTab();
      await navigate(tabId, `${BASE_URL}/x`, 1000);
      await navigate(tabId, `${BASE_URL}/y`, 1000);
      assert.equal(fake.updated.size, 0);
      assert.equal(fake.removed.size, 0);
    });
  });
});

describe('work_tab.runInTab: rezultatul și erorile măsurate în Edge 155', () => {
  test('trimite funcția în lumea izolată, cu argumentele, și întoarce rezultatul primului cadru', async () => {
    await withChrome({}, async (fake) => {
      const result = await runInTab(5, pageLastPageHint, [1, 'a']);
      assert.deepEqual(result, { eco: [1, 'a'] });
      assert.deepEqual(fake.scriptingCalls[0], { target: { tabId: 5 }, func: pageLastPageHint, args: [1, 'a'], world: 'ISOLATED' });
    });
  });

  test('„No tab with id” (cu sau fără punct) înseamnă fila închisă', async () => {
    for (const message of ['No tab with id: 5', 'No tab with id: 5.', 'The tab was closed.']) {
      await withChrome({ scriptError: message }, async () => {
        await assert.rejects(runInTab(5, pageLastPageHint), WorkTabClosed);
      });
    }
  });

  test('„Cannot access contents of the page” înseamnă pagină inaccesibilă (gazdă fără permisiune)', async () => {
    await withChrome({ scriptError: 'Cannot access contents of the page. Extension manifest must request permission to access the respective host.' }, async () => {
      await assert.rejects(runInTab(5, pageLastPageHint), PageNotAccessible);
    });
  });

  test('„Frame with ID 0 was removed”: fila închisă dacă nu mai există, altfel pagina s-a schimbat în timpul citirii', async () => {
    await withChrome({ scriptError: 'Frame with ID 0 was removed.' }, async (fake) => {
      await assert.rejects(runInTab(5, pageLastPageHint), WorkTabClosed);
      const tabId = await openWorkTab();
      await assert.rejects(runInTab(tabId, pageLastPageHint), PageNotAccessible);
      assert.ok(fake.tabs.has(tabId));
    });
  });

  test('nicio injecție (listă goală) este pagină inaccesibilă', async () => {
    await withChrome({ scriptResults: [] }, async () => {
      await assert.rejects(runInTab(5, pageLastPageHint), PageNotAccessible);
    });
  });

  test('rezultat null (funcția a aruncat în pagină sau n-a întors nimic) trece ca null', async () => {
    await withChrome({ scriptResults: [{ frameId: 0, result: null }] }, async () => {
      assert.equal(await runInTab(5, pageLastPageHint), null);
    });
  });

  test('altă eroare a lui Chrome trece mai departe cu mesajul ei', async () => {
    await withChrome({ scriptError: 'ceva neașteptat' }, async () => {
      await assert.rejects(runInTab(5, pageLastPageHint), /ceva neașteptat/);
    });
  });
});

// Teste unitare pentru extensie/src/colectare/waiting.js: `sleep` și `now`, cu pauzele făcute într-un Worker.
// De ce un Worker: măsurat pe 14.10.2026 în Edge 155, o pagină a extensiei ascunsă mai mult de 5 minute primește cronometrele (setTimeout, setInterval, și cu un Web Lock ținut) doar o dată pe minut,
// pe când cronometrul dintr-un Worker merge nereduse (~9 bătăi din 10 pe secundă). O analiză lungă, cu omul în altă filă, ar fi durat ore dacă pauzele din colectare (700 ms între citiri) ar fi rămas pe setTimeout.
// Aici: Worker fals (mesaje { id, ms } -> id), pauze simultane, rezerva pe setTimeout când nu există Worker sau nu se poate crea. Fiecare test importă o copie proaspătă a modulului (starea lui e un singur Worker pe pagină).
// Ce NU face: nu probează reducerea cronometrelor (asta cere un browser ascuns minute întregi; măsurătoarea e în raportul agentului).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

let copies = 0;
/** O copie proaspătă a modulului (altă adresă de import), ca fiecare test să pornească fără Worker creat. */
async function freshWaiting() {
  copies += 1;
  return import(`../../src/colectare/waiting.js?copie=${copies}`);
}

/** Pune un Worker fals global cât durează `body`; `behavior(worker)` poate răspunde singur la mesaje. */
async function withWorker(behavior, body) {
  const created = [];
  /** Worker fals: notează mesajele primite și lasă testul să răspundă cu `reply(id)`. */
  class FakeWorker {
    constructor(url) {
      this.url = String(url);
      this.messages = [];
      this.onmessage = null;
      created.push(this);
      behavior?.(this);
    }

    postMessage(message) {
      this.messages.push(message);
    }

    reply(id) {
      this.onmessage({ data: id });
    }
  }
  const previous = globalThis.Worker;
  globalThis.Worker = FakeWorker;
  try {
    return await body(created);
  } finally {
    if (previous === undefined) delete globalThis.Worker;
    else globalThis.Worker = previous;
  }
}

describe('sleep: pauza se face în Worker, ca să nu depindă de cronometrele paginii', () => {
  test('cere pauza Worker-ului (cu un id și durata) și se termină abia când el răspunde cu același id', async () => {
    await withWorker(null, async (created) => {
      const { sleep } = await freshWaiting();
      let done = false;
      const pause = sleep(700).then(() => { done = true; });
      await Promise.resolve();
      assert.equal(created.length, 1);
      assert.match(created[0].url, /colectare\/timer_worker\.js$/);
      assert.equal(created[0].messages.length, 1);
      assert.equal(created[0].messages[0].ms, 700);
      assert.equal(done, false);
      created[0].reply(created[0].messages[0].id);
      await pause;
      assert.equal(done, true);
    });
  });

  test('pauzele simultane au id-uri diferite și se termină fiecare la răspunsul ei, în orice ordine', async () => {
    await withWorker(null, async (created) => {
      const { sleep } = await freshWaiting();
      const finished = [];
      const first = sleep(100).then(() => finished.push('prima'));
      const second = sleep(200).then(() => finished.push('a doua'));
      await Promise.resolve();
      const [one, two] = created[0].messages;
      assert.notEqual(one.id, two.id);
      created[0].reply(two.id);
      await second;
      assert.deepEqual(finished, ['a doua']);
      created[0].reply(one.id);
      await first;
      assert.deepEqual(finished, ['a doua', 'prima']);
    });
  });

  test('un singur Worker pe pagină, creat abia la prima pauză', async () => {
    await withWorker(null, async (created) => {
      const { sleep } = await freshWaiting();
      assert.equal(created.length, 0);
      sleep(1);
      sleep(1);
      sleep(1);
      assert.equal(created.length, 1);
    });
  });

  test('un răspuns pentru un id necunoscut sau repetat nu strică nimic', async () => {
    await withWorker(null, async (created) => {
      const { sleep } = await freshWaiting();
      const pause = sleep(5);
      await Promise.resolve();
      const { id } = created[0].messages[0];
      created[0].reply(9999);
      created[0].reply(id);
      created[0].reply(id);
      await pause;
    });
  });

  test('fără Worker (Node, teste) pauza merge pe setTimeout și durează cel puțin atât cât s-a cerut', async () => {
    const { sleep } = await freshWaiting();
    const started = Date.now();
    await sleep(30);
    assert.ok(Date.now() - started >= 25);
  });

  test('dacă Worker-ul nu se poate crea (politică de conținut, eroare), pauza cade pe setTimeout, nu se blochează', async () => {
    const previous = globalThis.Worker;
    globalThis.Worker = class { constructor() { throw new Error('Worker interzis'); } };
    try {
      const { sleep } = await freshWaiting();
      const started = Date.now();
      await sleep(30);
      assert.ok(Date.now() - started >= 25);
    } finally {
      if (previous === undefined) delete globalThis.Worker;
      else globalThis.Worker = previous;
    }
  });

  test('o eroare a Worker-ului în timpul unei pauze nu o lasă agățată: pauzele în așteptare se termină pe setTimeout', async () => {
    await withWorker(null, async (created) => {
      const { sleep } = await freshWaiting();
      const started = Date.now();
      const pause = sleep(40);
      await Promise.resolve();
      created[0].onerror({ message: 'căzut' });
      await pause;
      assert.ok(Date.now() - started >= 30);
    });
  });
});

describe('now: ora curentă în milisecunde', () => {
  test('e Date.now()', async () => {
    const { now } = await freshWaiting();
    const before = Date.now();
    const value = now();
    assert.ok(value >= before && value <= Date.now());
  });
});

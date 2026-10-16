// Paritatea setărilor și determinismul generatorului: (1) generatorul scrie aceiași octeți la două rulări cu semințe de hash diferite (dovadă că ieșirile
// nu depind de ordinea seturilor din Python); (2) src/settings.js are aceleași nume și valori ca emag_spend/settings.py; (3) constantele de modul portate
// (praguri, limite, tipuri de avertismente, texte) sunt identice cu cele din Python, în modulele care există deja.
// Ce NU face: nu verifică logica modulelor (primitive.test.js) și nu pornește browser. Constantele din modulele agenților B și C se verifică de îndată ce modulele apar.
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { runGenerator } from '../../scripts/ruleaza_python.mjs';
import * as settings from '../../src/settings.js';
import { loadFixture, same } from '../fixturi.js';

const CALCUL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'src', 'calcul');
// Cele nouă fișiere pe care le scrie generatorul; unul lipsă sau în plus înseamnă că generatorul și testele nu mai sunt la fel.
const EXPECTED_FILES = ['analiza.json', 'difflib.json', 'html.json', 'parsere.json', 'primitive.json', 'regex.json', 'regex_aleatoare.json', 'setari.json', 'unicode.json'];
// Semințe de hash pentru cele două rulări; diferite, ca ordinea de iterare a seturilor de text să difere între ele dacă ieșirea ar depinde de ea.
const HASH_SEEDS = [0, 12345];
// Cât poate dura o rulare a generatorului pe un calculator lent înainte să o considerăm blocată.
const GENERATOR_TIMEOUT_MS = 300_000;

describe('generatorul de fixturi', () => {
  test('rulat de două ori, cu PYTHONHASHSEED diferit, scrie aceiași octeți', { timeout: 2 * GENERATOR_TIMEOUT_MS }, () => {
    const folders = HASH_SEEDS.map((seed) => mkdtempSync(path.join(os.tmpdir(), `paritate-${seed}-`)));
    try {
      HASH_SEEDS.forEach((seed, index) => {
        const result = runGenerator(folders[index], { hashSeed: seed, stdio: 'pipe' });
        assert.equal(result.error, undefined, `nu pot porni Python: ${result.error?.message}`);
        assert.equal(result.status, 0, `generatorul a ieșit cu ${result.status} (sămânța ${seed}):\n${result.stderr}`);
      });
      const [first, second] = folders.map((folder) => readdirSync(folder).sort());
      assert.deepEqual(first, EXPECTED_FILES);
      assert.deepEqual(second, EXPECTED_FILES);
      for (const name of EXPECTED_FILES) {
        const left = readFileSync(path.join(folders[0], name));
        const right = readFileSync(path.join(folders[1], name));
        assert.ok(left.equals(right), `${name} diferă între semințele ${HASH_SEEDS.join(' și ')}: ieșirea Python depinde de ordinea seturilor`);
        assert.ok(left.length > 100, `${name} e prea mic ca să fie o fixtură`);
      }
    } finally {
      for (const folder of folders) rmSync(folder, { recursive: true, force: true });
    }
  });
});

describe('src/settings.js față de emag_spend/settings.py', () => {
  const fixture = loadFixture('setari');
  for (const [name, expected] of Object.entries(fixture.settings)) {
    test(`${name} = ${JSON.stringify(expected)}`, () => {
      assert.ok(Object.hasOwn(settings, name), `src/settings.js nu exportă ${name}`);
      same(settings[name], expected, () => name);
    });
  }
  test('orderListPagePath și orderDetailPath dau căile din Python', () => {
    for (const { page, out } of fixture.paths.order_list_page) same(settings.orderListPagePath(page), out, () => `orderListPagePath(${page})`);
    for (const { order_id: orderId, out } of fixture.paths.order_detail) same(settings.orderDetailPath(orderId), out, () => `orderDetailPath(${JSON.stringify(orderId)})`);
  });
  test('src/settings.js nu exportă nimic ce nu există în Python (nicio setare inventată)', () => {
    const extra = Object.keys(settings).filter((name) => !Object.hasOwn(fixture.settings, name) && !['orderListPagePath', 'orderDetailPath'].includes(name));
    assert.deepEqual(extra, []);
  });
});

describe('forma fixturilor html, parsere și analiza, pe care se sprijină agenții B și C', () => {
  test('html.json: fiecare pagină are nume, html, linii și nume_produse; numele sunt unice', () => {
    const { pagini } = loadFixture('html');
    assert.ok(pagini.length >= 90, `doar ${pagini.length} pagini`);
    assert.equal(new Set(pagini.map((page) => page.nume)).size, pagini.length);
    for (const page of pagini) {
      assert.deepEqual(Object.keys(page), ['nume', 'html', 'linii', 'nume_produse'], page.nume);
      assert.ok(Array.isArray(page.linii) && Array.isArray(page.nume_produse), page.nume);
    }
    for (const prefix of ['comanda_simpla_inline', 'comanda_simpla_stacked', 'comanda_pachet_inline', 'retur_finalizat_cu_suma_doua_linii', 'retur_finalizat_cu_suma_o_linie', 'capcana_entitati']) {
      assert.ok(pagini.some((page) => page.nume === prefix), `lipsește pagina ${prefix}`);
    }
  });
  test('parsere.json: cazuri de comandă și de retur, cu rezultat sau cu eroare (nu amândouă), inclusiv variante stricate', () => {
    const { cazuri } = loadFixture('parsere');
    assert.ok(cazuri.length >= 600, `doar ${cazuri.length} cazuri`);
    assert.equal(new Set(cazuri.map((caz) => caz.nume)).size, cazuri.length, 'numele cazurilor trebuie să fie unice');
    for (const caz of cazuri) {
      assert.ok(['comanda', 'retur'].includes(caz.tip), caz.nume);
      assert.equal('rezultat' in caz, !('eroare' in caz), `${caz.nume}: exact unul dintre rezultat / eroare`);
      assert.ok(Array.isArray(caz.linii) && typeof caz.id_sau_cale === 'string', caz.nume);
      assert.ok(caz.nume_produse === null || Array.isArray(caz.nume_produse), caz.nume);
    }
    assert.ok(cazuri.some((caz) => caz.eroare?.mesaj.includes("nu conține 'Comanda nr.'")), 'trebuie să existe și cazuri de eroare la comandă');
    assert.ok(cazuri.some((caz) => caz.eroare?.mesaj.includes("nu conține 'Retur #'")), 'trebuie să existe și cazuri de eroare la retur');
    assert.ok(cazuri.filter((caz) => caz.nume.startsWith('mutant_')).length >= 500);
  });
  test('analiza.json: scenariile cerute, cu toate cheile și cu CSV-urile cu BOM', () => {
    const { scenarii } = loadFixture('analiza');
    const names = scenarii.map((scenario) => scenario.nume);
    for (const required of ['scenariu', 'demo', 'din_pagini', 'capcane_sortare', 'capcane_preturi', 'capcane_retururi', 'capcane_sume']) assert.ok(names.includes(required), `lipsește scenariul ${required}`);
    const keys = ['nume', 'comenzi', 'retururi', 'reguli', 'prag_bani', 'generat_la', 'evidentiate', 'rezumat', 'linii'];
    for (const scenario of scenarii) {
      for (const key of [...keys, 'linii_csv', 'istoric_csv', 'comenzi_json', 'retururi_json']) assert.ok(key in scenario, `${scenario.nume}: lipsește ${key}`);
      assert.ok(scenario.linii_csv.startsWith('\u{feff}comanda;'), `${scenario.nume}: produse.csv începe cu BOM și capul de tabel`);
      assert.ok(scenario.istoric_csv.startsWith('\u{feff}produs;'), `${scenario.nume}: istoric_preturi.csv începe cu BOM și capul de tabel`);
      assert.deepEqual(JSON.parse(scenario.comenzi_json), scenario.comenzi, `${scenario.nume}: comenzi_json`);
      assert.deepEqual(JSON.parse(scenario.retururi_json), scenario.retururi, `${scenario.nume}: retururi_json`);
      assert.equal(scenario.rezumat.meta.orders, scenario.comenzi.length, `${scenario.nume}: rezumat.meta.orders`);
      assert.equal(scenario.rezumat.meta.lines, scenario.linii.length, `${scenario.nume}: rezumat.meta.lines`);
    }
    const main = scenarii.find((scenario) => scenario.nume === 'scenariu');
    assert.ok(main.raport_html.includes('<script') && main.raport_html.length > 100_000, 'scenariu are raportul HTML complet');
  });
});

describe('constantele de modul portate', () => {
  const fixture = loadFixture('setari');
  for (const [moduleName, constants] of Object.entries(fixture.module_constants)) {
    test(`${moduleName}: ${Object.keys(constants).join(', ')}`, async (t) => {
      const file = path.join(CALCUL_DIR, `${moduleName}.js`);
      if (!existsSync(file)) {
        t.skip(`${moduleName}.js nu există încă (îl scrie un alt agent); constantele se verifică de îndată ce apare`);
        return;
      }
      const loaded = await import(pathToFileURL(file).href);
      for (const [name, expected] of Object.entries(constants)) {
        assert.ok(Object.hasOwn(loaded, name), `${moduleName}.js nu exportă ${name}`);
        same(loaded[name], expected, () => `${moduleName}.${name}`);
      }
    });
  }
});

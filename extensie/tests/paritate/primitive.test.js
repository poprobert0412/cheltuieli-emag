// Paritatea Python <-> JavaScript pe primitive: python_compat, text_normalize, money_ro, dates_ro, proportional_split, block_status, warning_messages, order_links, models,
// expresiile regulate (python_regex pe config/categorii.json și pe expresiile interne ale modulelor) și SequenceMatcher (difflib).
// Fiecare caz vine din tests/paritate_export.py (ieșirea EXACTĂ a lui Python: valoare sau eroare cu mesaj) și se cere identic: numerele cu Object.is (cu -0), listele în aceeași ordine.
// Ce NU face: nu testează pagini sau analiză (acelea sunt în testele agenților B și C), nici tabelele Unicode (unicode.test.js).
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import * as blockStatus from '../../src/calcul/block_status.js';
import * as datesRo from '../../src/calcul/dates_ro.js';
import * as models from '../../src/calcul/models.js';
import * as moneyRo from '../../src/calcul/money_ro.js';
import * as orderLinks from '../../src/calcul/order_links.js';
import * as compat from '../../src/calcul/python_compat.js';
import { PatternSyntaxError, PyPattern, UnsupportedPattern, escapePython } from '../../src/calcul/python_regex.js';
import { SequenceMatcher, getCloseMatches } from '../../src/calcul/sequence_matcher.js';
import { splitProportionally } from '../../src/calcul/proportional_split.js';
import { normalizeText } from '../../src/calcul/text_normalize.js';
import * as warningMessages from '../../src/calcul/warning_messages.js';
import { attempt, loadFixture, same, sameError, sameOutcome, snakeToCamel } from '../fixturi.js';

const primitive = loadFixture('primitive');
const show = (value) => JSON.stringify(value);

/** Un test pe secțiune: ruleaza `check(caz)` pe fiecare caz și spune câte cazuri a trecut (afișat ca diagnostic). */
function eachCase(name, cases, check) {
  test(`${name} (${cases.length} cazuri)`, (t) => {
    assert.ok(cases.length > 0, `secțiunea ${name} e goală: testul n-ar dovedi nimic`);
    for (const entry of cases) check(entry);
    t.diagnostic(`${cases.length} cazuri identice cu Python`);
  });
}

describe('text_normalize, money_ro, dates_ro, block_status', () => {
  eachCase('normalize_text', primitive.normalize_text, (c) => {
    same(normalizeText(c.in), c.out, () => `normalize_text(${show(c.in)})`);
  });
  eachCase('ro_amount_to_bani', primitive.ro_amount_to_bani, (c) => {
    sameOutcome(attempt(() => moneyRo.roAmountToBani(c.in)), c, () => `ro_amount_to_bani(${show(c.in)})`);
  });
  eachCase('parse_full_amount', primitive.parse_full_amount, (c) => same(moneyRo.parseFullAmount(c.in), c.out, () => `parse_full_amount(${show(c.in)})`));
  eachCase('find_amount', primitive.find_amount, (c) => same(moneyRo.findAmount(c.in), c.out, () => `find_amount(${show(c.in)})`));
  eachCase('find_last_amount', primitive.find_last_amount, (c) => same(moneyRo.findLastAmount(c.in), c.out, () => `find_last_amount(${show(c.in)})`));
  eachCase('parse_refund_amount', primitive.parse_refund_amount, (c) => same(moneyRo.parseRefundAmount(c.in), c.out, () => `parse_refund_amount(${show(c.in)})`));
  eachCase('format_lei', primitive.format_lei, (c) => same(moneyRo.formatLei(c.in), c.out, () => `format_lei(${c.in})`));
  eachCase('parse_ro_datetime', primitive.parse_ro_datetime, (c) => same(datesRo.parseRoDatetime(c.in), c.out, () => `parse_ro_datetime(${show(c.in)})`));
  eachCase('classify_status', primitive.classify_status, (c) => same(blockStatus.classifyStatus(c.in), c.out, () => `classify_status(${show(c.in)})`));
});

describe('proportional_split', () => {
  eachCase('split_proportionally', primitive.split_proportionally, (c) => {
    sameOutcome(attempt(() => splitProportionally(c.total, c.weights)), c, () => `split_proportionally(${c.total}, ${show(c.weights)})`);
  });
});

describe('python_compat: rotunjire, // și %, sortări, strip/split, int, json, csv, repr', () => {
  eachCase('round(x, n)', primitive.round_float, (c) => {
    sameOutcome(attempt(() => compat.pyRound(c.x, c.ndigits)), c, () => `round(${c.x}, ${c.ndigits})`);
  });
  eachCase('round(x)', primitive.round_int, (c) => {
    sameOutcome(attempt(() => compat.pyRoundInt(c.x)), c, () => `round(${c.x})`);
  });
  eachCase('round(delta * 100 / preț, 1) ca la last_vs_prev_pct', primitive.percent, (c) => {
    same(compat.pyRound((c.delta * 100) / c.previous, 1), c.out, () => `round(${c.delta} * 100 / ${c.previous}, 1)`);
  });
  eachCase('// și %', primitive.division, (c) => {
    if (c.zero_division) {
      assert.throws(() => compat.floorDiv(c.a, c.b), RangeError);
      assert.throws(() => compat.pyMod(c.a, c.b), RangeError);
    } else {
      same([compat.floorDiv(c.a, c.b), compat.pyMod(c.a, c.b)], [c.div, c.mod], () => `${c.a} // ${c.b} și ${c.a} % ${c.b}`);
    }
  });
  eachCase('sorted(texte)', primitive.ordering.strings, (c) => {
    same(compat.sortedBy(c.in), c.out, () => `sorted(${show(c.in)})`);
  });
  eachCase('comparație de texte (cmp)', primitive.ordering.compare, (c) => {
    same(compat.compareCodePoints(c.a, c.b), c.out, () => `cmp(${show(c.a)}, ${show(c.b)})`);
  });
  eachCase('sorted/max/min cu chei-tuplu', primitive.ordering.tuples, (c) => {
    const indices = c.keys.map((_, index) => index);
    if (c.out) same(compat.sortedBy(indices, (index) => c.keys[index], { reverse: c.reverse }), c.out, () => `sorted(${show(c.keys)}, reverse=${c.reverse})`);
    if (c.max_index !== undefined) {
      same(compat.maxBy(indices, (index) => c.keys[index]), c.max_index, () => `max(${show(c.keys)})`);
      same(compat.minBy(indices, (index) => c.keys[index]), c.min_index, () => `min(${show(c.keys)})`);
    }
  });
  eachCase('sorted/max cu chei scalare', primitive.ordering.scalars, (c) => {
    const indices = c.keys.map((_, index) => index);
    same(compat.sortedBy(indices, (index) => c.keys[index]), c.out, () => `sorted(${show(c.keys)})`);
    same(compat.maxBy(indices, (index) => c.keys[index]), c.max_index, () => `max(${show(c.keys)})`);
  });
  eachCase('chei amestecate: TypeError', primitive.ordering.mixed, (c) => {
    assert.equal(c.error.type, 'TypeError');
    const indices = c.keys.map((_, index) => index);
    assert.throws(() => compat.sortedBy(indices, (index) => c.keys[index]), TypeError, show(c.keys));
  });
  eachCase('strip / lstrip / rstrip / split', primitive.strip_split, (c) => {
    same(compat.pyStrip(c.in), c.strip, () => `strip(${show(c.in)})`);
    same(compat.pyLstrip(c.in), c.lstrip, () => `lstrip(${show(c.in)})`);
    same(compat.pyRstrip(c.in), c.rstrip, () => `rstrip(${show(c.in)})`);
    same(compat.pySplit(c.in), c.split, () => `split(${show(c.in)})`);
    for (const withChars of c.with_chars) {
      same(compat.pyStrip(c.in, withChars.chars), withChars.strip, () => `strip(${show(c.in)}, ${show(withChars.chars)})`);
      same(compat.pyLstrip(c.in, withChars.chars), withChars.lstrip, () => `lstrip(${show(c.in)}, ${show(withChars.chars)})`);
      same(compat.pyRstrip(c.in, withChars.chars), withChars.rstrip, () => `rstrip(${show(c.in)}, ${show(withChars.chars)})`);
    }
  });
  eachCase('int(text)', primitive.int, (c) => {
    // Python are întregi oricât de mari; peste 2^53 JS refuză cu RangeError (documentat în pyInt), deci acolo nu se compară valoarea
    if (c.out !== undefined && !Number.isSafeInteger(c.out)) {
      assert.throws(() => compat.pyInt(c.in), RangeError, show(c.in));
    } else {
      sameOutcome(attempt(() => compat.pyInt(c.in)), c, () => `int(${show(c.in)})`);
    }
  });
  eachCase('json.dumps(valoare, ensure_ascii=False, indent=1) și cu separatori impliciți', primitive.json.plain, (c) => {
    same(compat.pyJsonDumps(c.value, { indent: c.indent === undefined ? 1 : c.indent }), c.out, () => `json.dumps(${show(c.value)}, indent=${show(c.indent ?? 1)})`);
  });
  eachCase('json.dumps pe dicționare cu chei din date (Map)', primitive.json.maps, (c) => {
    same(compat.pyJsonDumps(new Map(c.pairs), { indent: c.indent === undefined ? 1 : c.indent }), c.out, () => `json.dumps(dict(${show(c.pairs)}))`);
  });
  eachCase('json.dumps cu numere cu fracții', primitive.json.fractions, (c) => {
    same(compat.pyJsonDumps(c.value, { indent: c.indent === undefined ? 1 : c.indent, fractions: true }), c.out, () => `json.dumps(${show(c.value)})`);
  });
  eachCase('repr(float)', primitive.json.float_repr, (c) => same(compat.pyFloatRepr(c.x), c.out, () => `repr(${c.x})`));
  eachCase('PyFloat: json.dumps și repr pe liste și dicționare cu floaturi, inclusiv cu valoare întreagă (5.0)', primitive.json.float_marked, (c) => {
    const floats = c.values.map((value) => new compat.PyFloat(value));
    same(compat.pyJsonDumps(floats), c.list_out, () => `json.dumps(${show(c.values)}, indent=1)`);
    same(compat.pyJsonDumps(floats, { indent: null }), c.list_flat_out, () => `json.dumps(${show(c.values)})`);
    same(compat.pyJsonDumps({ pct: floats[0], n: 3, xs: floats.slice(1) }), c.dict_out, () => `json.dumps({"pct": ${show(c.values[0])}, "n": 3, "xs": ...}, indent=1)`);
    same(compat.pyRepr(floats), c.repr_out, () => `repr(${show(c.values)})`);
  });
  eachCase('csv.writer(delimiter=";").writerow', primitive.csv_row, (c) => {
    const fields = c.fields.map((field, index) => (c.float_at?.includes(index) ? new compat.PyFloat(field) : field)); // JSON nu face diferența între 5.0 și 5: `float_at` spune care sunt float
    same(compat.pyCsvRow(fields), c.out, () => `writerow(${show(c.fields)}) cu float pe pozițiile ${show(c.float_at ?? [])}`);
  });
  eachCase('repr(valoare)', primitive.repr, (c) => {
    same(compat.pyRepr(c.value), c.out, () => `repr(${show(c.value)})`);
  });
  eachCase('re.escape', primitive.escape, (c) => same(escapePython(c.in), c.out, () => `re.escape(${show(c.in)})`));
  eachCase('re.sub cu șabloane la întâmplare: același rezultat sau aceeași eroare ca Python (mesaj, poziție, ordinea erorilor)', primitive.sub_templates, (c) => {
    const got = attempt(() => new PyPattern(c.pattern).sub(c.template, c.text, c.count));
    sameOutcome(got, c, () => `re.sub(${show(c.pattern)}, ${show(c.template)}, ${show(c.text)}, count=${c.count})`);
  });
});

describe('warning_messages, order_links', () => {
  eachCase('format_* din warning_messages', primitive.warning_formats, (c) => {
    same(warningMessages[snakeToCamel(c.fn)](...c.args), c.out, () => `${c.fn}(${show(c.args)})`);
  });
  eachCase('parse_order_warning', primitive.parse_order_warning, (c) => {
    same(warningMessages.parseOrderWarning(c.in), c.out, () => `parse_order_warning(${show(c.in)})`);
  });
  eachCase('order_links', primitive.order_links, (c) => {
    same(orderLinks[snakeToCamel(c.fn)](...c.args), c.out, () => `${c.fn}(${show(c.args)})`);
  });
});

describe('models: LineOutcome, Item/SellerBlock/Order/ReturnRequest din dict', () => {
  eachCase('LineOutcome: câmpuri, to_dict și proprietăți', primitive.line_outcome, (c) => {
    const line = new models.LineOutcome(c.fields);
    same(line.toDict(), c.dict, () => `to_dict pentru ${show(c.fields)}`);
    same(models.toDict(line), c.dict, () => `toDict pentru ${show(c.fields)}`);
    for (const [name, expected] of Object.entries(c.properties)) {
      same(line[name], expected, () => `${name} pentru ${show(c.fields)}`);
    }
  });
  eachCase('order_from_dict / return_from_dict / to_dict / Order.year', primitive.models_dict, (c) => {
    const build = c.kind === 'order' ? models.orderFromDict : models.returnFromDict;
    if (c.error) {
      sameError(attempt(() => build(c.dict)), c.error, () => `${c.name}: ${c.kind}_from_dict`);
      return;
    }
    const built = build(c.dict);
    same(models.toDict(built), c.out, () => `${c.name}: to_dict(${c.kind}_from_dict(...))`);
    if (c.kind === 'order') sameOutcome(attempt(() => models.orderYear(built)), c.year, () => `${c.name}: Order.year`);
  });
  test('Item, SellerBlock, Order și ReturnRequest au câmpurile în ordinea din Python și valorile implicite proaspete', () => {
    const block = models.makeSellerBlock({ seller: 'eMAG', status: 'DELIVERED', status_text: 'x', has_storno: false });
    assert.deepEqual(Object.keys(block), ['seller', 'status', 'status_text', 'has_storno', 'items', 'products_total_bani', 'vouchers_bani', 'shipping_bani', 'services_bani', 'other_bani', 'paid_bani', 'due_bani']);
    const other = models.makeSellerBlock({ seller: 'eMAG', status: 'DELIVERED', status_text: 'x', has_storno: false });
    assert.notEqual(block.items, other.items, 'fiecare bloc are lista lui (default_factory)');
    assert.deepEqual(Object.keys(models.makeOrder({ order_id: '1', placed_text: '', placed_at: null, header_total_bani: null })), ['order_id', 'placed_text', 'placed_at', 'header_total_bani', 'blocks', 'warnings']);
    assert.deepEqual(models.makeItem('x', 100, 2), { name: 'x', line_total_bani: 100, qty: 2 });
    assert.deepEqual(Object.keys(models.makeReturnRequest({
      return_id: '1', detail_path: '/x', order_ids: [], product_names: [], steps: [], refund_bani: null, refund_mode: '', completed: false, cancelled: false,
    })), ['return_id', 'detail_path', 'order_ids', 'product_names', 'steps', 'refund_bani', 'refund_mode', 'completed', 'cancelled']);
  });
});

describe('python_regex pe regulile din config/categorii.json și pe expresiile interne ale modulelor', () => {
  const regex = loadFixture('regex');

  test(`modelele din config/categorii.json și categorii.personal.exemplu.json: ${regex.modele.length} modele pe ${regex.corpus.length} de texte`, (t) => {
    assert.ok(regex.modele.length >= 400 && regex.corpus.length >= 300, 'fixtura regex e prea mică ca să dovedească ceva');
    for (const rule of regex.modele) {
      const pattern = new PyPattern(rule.model);
      const hits = [];
      regex.corpus.forEach((text, index) => {
        if (pattern.search(text) !== null) hits.push(index);
      });
      same(hits, rule.potriviri, () => `${rule.fisier} / ${rule.categorie} / ${rule.tip}: ${show(rule.model)}`);
    }
    t.diagnostic(`${regex.modele.length} modele identice cu Python pe ${regex.corpus.length} de texte`);
  });

  const describeMatch = (match) => (match === null ? null : { span: match.span(), groups: match.groups(), groupdict: match.groupdict() });
  for (const expression of regex.interne) {
    test(`${expression.nume}: ${expression.texte.length} texte, toate metodele`, () => {
      const pattern = new PyPattern(expression.sursa, { ignoreCase: expression.ignore_case, dotAll: expression.dot_all });
      for (const item of expression.texte) {
        const label = () => `${expression.nume} pe ${show(item.text)}`;
        same(describeMatch(pattern.search(item.text)), item.search, () => `${label()}: search`);
        same(describeMatch(pattern.match(item.text)), item.match, () => `${label()}: match`);
        same(describeMatch(pattern.fullmatch(item.text)), item.fullmatch, () => `${label()}: fullmatch`);
        same(pattern.findall(item.text), item.findall, () => `${label()}: findall`);
        same(pattern.finditer(item.text).map(describeMatch), item.finditer, () => `${label()}: finditer`);
        same(pattern.sub(' ', item.text), item.sub_spatiu, () => `${label()}: sub(' ')`);
        same(pattern.sub('', item.text, 1), item.sub_gol_unu, () => `${label()}: sub('', count=1)`);
        same(pattern.split(item.text), item.split, () => `${label()}: split`);
      }
    });
  }

  test('expresii invalide: același mesaj ca re.error', () => {
    assert.ok(regex.invalide.length > 20);
    for (const invalid of regex.invalide) {
      assert.throws(() => new PyPattern(invalid.sursa), (error) => error.name === 'PatternSyntaxError' && error.message === invalid.mesaj, `${show(invalid.sursa)} -> ${invalid.mesaj}`);
    }
  });

  test('construcții valide în Python, dar refuzate de port: UnsupportedPattern cu numele construcției', () => {
    assert.ok(regex.refuzate.length > 15);
    for (const refused of regex.refuzate) { // numele fiecărei construcții e probat în tests/unit/python_regex.test.js
      assert.throws(() => new PyPattern(refused.sursa, { ignoreCase: refused.ignore_case }),
        (error) => error.name === 'UnsupportedPattern' && typeof error.construct === 'string', `${show(refused.sursa)} ignoreCase=${refused.ignore_case}`);
    }
  });
});

describe('sequence_matcher: difflib.SequenceMatcher și get_close_matches', () => {
  const difflib = loadFixture('difflib');
  test(`${difflib.pares.length} de perechi: ratio, quick_ratio, real_quick_ratio și blocurile potrivite, identice`, (t) => {
    assert.ok(difflib.pares.length >= 2000, 'fixtura difflib are mai puțin de 2000 de perechi');
    for (const pair of difflib.pares) {
      const matcher = new SequenceMatcher(pair.a, pair.b);
      const label = () => `SequenceMatcher(${show(pair.a)}, ${show(pair.b)})`;
      same(matcher.ratio(), pair.ratio, () => `${label()}.ratio`);
      same(matcher.quickRatio(), pair.quick_ratio, () => `${label()}.quick_ratio`);
      same(matcher.realQuickRatio(), pair.real_quick_ratio, () => `${label()}.real_quick_ratio`);
      same(matcher.getMatchingBlocks(), pair.blocuri, () => `${label()}.get_matching_blocks`);
    }
    t.diagnostic(`${difflib.pares.length} perechi identice cu Python`);
  });
  test(`${difflib.apropiate.length} de apeluri get_close_matches`, () => {
    assert.ok(difflib.apropiate.length >= 100);
    for (const call of difflib.apropiate) {
      same(getCloseMatches(call.cuvant, call.posibilitati, call.n, call.cutoff), call.rezultat, () => `get_close_matches(${show(call.cuvant)}, ${show(call.posibilitati)}, n=${call.n}, cutoff=${call.cutoff})`);
    }
  });
  test(`${difflib.scriptate.length} de scenarii get_matching_blocks cu find_longest_match scriptat: coada de regiuni și unirea blocurilor adiacente`, () => {
    // Cu isjunk = None un find_longest_match real nu dă niciodată blocuri adiacente, deci unirea lor se probează doar cu răspunsuri date din tabelul scris de Python.
    assert.ok(difflib.scriptate.length >= 300, 'fixtura difflib are mai puțin de 300 de scenarii scriptate');
    assert.ok(difflib.scriptate.filter((scenario) => scenario.unite).length >= 60, 'prea puține scenarii cu blocuri care se unesc: ramura de unire n-ar fi probată');
    for (const scenario of difflib.scriptate) {
      const answers = new Map(scenario.tabel.map(([alo, ahi, blo, bhi, i, j, k]) => [`${alo},${ahi},${blo},${bhi}`, [i, j, k]]));
      const asked = new Set();
      class ScriptedMatcher extends SequenceMatcher {
        /** Răspunde din tabelul scris de Python (regiunea cerută -> blocul dat), fără să caute: probează doar coada de regiuni și unirea blocurilor. */
        findLongestMatch(alo = 0, ahi = null, blo = 0, bhi = null) {
          const key = `${alo},${ahi},${blo},${bhi}`;
          assert.ok(answers.has(key), `regiune neașteptată ${key}: coada de regiuni diferă de cea din Python`);
          assert.ok(!asked.has(key), `regiunea ${key} cerută de două ori`);
          asked.add(key);
          return [...answers.get(key)];
        }
      }
      const matcher = new ScriptedMatcher('a'.repeat(scenario.lungime_a), 'b'.repeat(scenario.lungime_b));
      same(matcher.getMatchingBlocks(), scenario.blocuri, () => `get_matching_blocks cu tabelul ${show(scenario.tabel)}`);
      assert.equal(asked.size, answers.size, `regiuni din tabel rămase necerute: ${show(scenario.tabel)}`);
    }
  });
});

describe('python_regex: expresii generate la întâmplare, față de re din Python', () => {
  const random = loadFixture('regex_aleatoare');
  // Pragurile apără testul de a deveni inutil: dacă prea multe expresii ar fi refuzate, sau prea puține erori ar avea mesajul identic cu al lui Python, testul n-ar mai dovedi nimic.
  const MIN_COMPARED_SHARE = 0.5;
  const MIN_MATCHED_ERRORS_SHARE = 0.8;
  const describeMatch = (match) => (match === null ? null : { span: match.span(), groups: match.groups(), groupdict: match.groupdict() });

  test(`${random.cazuri.length} de expresii: același rezultat sau aceeași eroare ca Python, ori o construcție refuzată cu numele ei`, (t) => {
    const count = { valid: 0, compared: 0, texts: 0, errors: 0, errorsMatched: 0, errorsRefusedFirst: 0 };
    const refused = new Map();
    for (const entry of random.cazuri) {
      const label = () => `/${entry.sursa}/ ignore_case=${entry.ignore_case} dot_all=${entry.dot_all}`;
      let pattern = null;
      let failure = null;
      try {
        pattern = new PyPattern(entry.sursa, { ignoreCase: entry.ignore_case, dotAll: entry.dot_all });
      } catch (error) {
        failure = error;
      }
      if (entry.eroare !== undefined) { // invalidă în Python: aceeași eroare, sau o construcție refuzată întâlnită înaintea greșelii (portul o semnalează prima)
        count.errors += 1;
        if (failure instanceof PatternSyntaxError) {
          same(failure.message, entry.eroare, () => `mesajul de eroare pentru ${label()}`);
          count.errorsMatched += 1;
        } else {
          assert.ok(failure instanceof UnsupportedPattern, `${label()}: Python dă «${entry.eroare}», portul ${failure ? `a ridicat ${failure.name}: ${failure.message}` : 'a acceptat expresia'}`);
          count.errorsRefusedFirst += 1;
        }
        continue;
      }
      count.valid += 1;
      if (failure !== null) { // validă în Python, refuzată de port: numai UnsupportedPattern, cu numele construcției
        assert.ok(failure instanceof UnsupportedPattern && typeof failure.construct === 'string', `${label()}: eroare neașteptată ${failure.name}: ${failure.message}`);
        refused.set(failure.construct, (refused.get(failure.construct) ?? 0) + 1);
        continue;
      }
      count.compared += 1;
      for (const item of entry.texte) {
        count.texts += 1;
        const label2 = (method) => () => `${label()}.${method}(${show(item.text)})`;
        same(describeMatch(pattern.search(item.text)), item.search, label2('search'));
        same(describeMatch(pattern.match(item.text)), item.match, label2('match'));
        same(describeMatch(pattern.fullmatch(item.text)), item.fullmatch, label2('fullmatch'));
        same(pattern.findall(item.text), item.findall, label2('findall'));
        same(pattern.finditer(item.text).map(describeMatch), item.finditer, label2('finditer'));
        same(pattern.sub(random.sablon, item.text), item.sub, label2('sub'));
        same(pattern.split(item.text), item.split, label2('split'));
        same(pattern.sub(random.sablon, item.text, 1), item.sub_unu, label2('sub(count=1)'));
        same(pattern.split(item.text, 1), item.split_unu, label2('split(maxsplit=1)'));
        same(pattern.split(item.text, 2), item.split_doi, label2('split(maxsplit=2)'));
      }
    }
    t.diagnostic(`${count.compared} din ${count.valid} expresii valide comparate pe ${count.texts} de texte; ${count.errorsMatched} din ${count.errors} erori cu mesaj identic, ${count.errorsRefusedFirst} cu o construcție refuzată înaintea greșelii`);
    t.diagnostic(`refuzate (valide în Python): ${[...refused].map(([construct, times]) => `${construct} x${times}`).join('; ')}`);
    assert.ok(count.compared >= MIN_COMPARED_SHARE * count.valid, `doar ${count.compared} din ${count.valid} expresii valide au fost comparate (restul refuzate): testul și-a pierdut valoarea`);
    assert.ok(count.errorsMatched >= MIN_MATCHED_ERRORS_SHARE * count.errors, `doar ${count.errorsMatched} din ${count.errors} mesaje de eroare sunt identice cu ale lui Python`);
  });
});

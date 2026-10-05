/* site-viewer.js — vizualizatorul de analiza.json: tragere + alegere de fișier, validare, raport în pagină.
 * Primește: un fișier (input, tragere oriunde în pagină) sau text lipit; EmagDashboard.validate/mount.
 * Dă înapoi: nimic; montează raportul în #viewer-mount, anunță rezultatul în #viewer-status (aria-live)
 * și ține starea în adresă: #incarca/raportul-tau sau #incarca/demo. Fișierul se citește local în browser.
 * Nu face nicio cerere de rețea. Datele încărcate nu se păstrează după închiderea paginii.
 */
(function (root) {
  'use strict';

  var Site = (root.Site = root.Site || {});
  var doc = root.document;

  var STATE_TOKEN = 'incarca';
  var SUB_MINE = 'raportul-tau';
  var SUB_DEMO = 'demo';
  var MAX_BYTES = 25 * 1024 * 1024; // un analiza.json obișnuit e mult mai mic; peste 25 MB e aproape sigur alt fișier
  var MAX_ERRORS_SHOWN = 6; // câte erori de schemă se listează; restul se numără
  var DEFER_DRAW_BYTES = 1024 * 1024; // un analiza.json obișnuit are sub 1 MB; peste el desenarea poate dura, deci mesajul „Se desenează…” trebuie să apuce să apară înaintea ei
  var REPORT_HEADING_LEVEL = 3; // secțiunea are h2: blocurile raportului sunt h3, cele din ele h4

  var els = {};
  var mine = null; // { name, size, data } după o încărcare reușită
  var shown = ''; // '' | 'mine' | 'demo'
  var instance = null;
  var drawToken = 0; // numărul ultimei încărcări: o desenare amânată a unui fișier mai vechi nu are voie să-l înlocuiască pe cel nou

  /** Anunță un rezultat în zona de stare (aria-live); `kind` = info | ok | error. */
  function setStatus(kind, nodes) {
    var h = Site.dom.h;
    Site.dom.clear(els.status);
    els.status.setAttribute('data-kind', kind);
    var prefix = kind === 'error' ? 'Eroare: ' : kind === 'ok' ? 'Gata: ' : '';
    els.status.appendChild(h('span', null, prefix, nodes));
  }

  /** Mesajul pentru un fișier de alt tip decât analiza.json, după nume; null dacă numele nu spune nimic. */
  function wrongFileHint(name) {
    if (/\.html?$/i.test(name)) return 'Ai ales „' + name + '”. Acesta se deschide direct în browser, cu dublu-click. Aici încarcă analiza.json din același folder.';
    if (/\.csv$/i.test(name)) return 'Ai ales „' + name + '”. Acesta se deschide în Excel. Aici încarcă analiza.json din același folder.';
    if (/\.txt$/i.test(name)) return 'Ai ales „' + name + '”. Acesta e doar un rezumat de citit. Aici încarcă analiza.json din același folder.';
    return null;
  }

  /** Dezmontează raportul afișat acum, dacă există. */
  function unmountCurrent() {
    if (instance && typeof instance.unmount === 'function') {
      try { instance.unmount(); } catch (e) { /* un unmount căzut nu trebuie să blocheze următorul raport */ }
    }
    instance = null;
    Site.dom.clear(els.mount);
  }

  /** Actualizează bara: butoanele, bannerul, titlul și eticheta ferestrei, după ce se vede acum. */
  function renderChrome() {
    var h = Site.dom.h;
    els.segMine.setAttribute('aria-pressed', String(shown === 'mine'));
    els.segMine.setAttribute('aria-disabled', String(!mine));
    els.segDemo.setAttribute('aria-pressed', String(shown === 'demo'));
    els.empty.hidden = shown !== '';
    els.mount.hidden = shown === '';
    els.banner.hidden = shown !== 'mine';
    Site.dom.clear(els.banner);
    if (shown === 'mine' && mine) {
      var generated = mine.data.meta && mine.data.meta.generated_at ? ' · generat ' + mine.data.meta.generated_at : '';
      els.banner.appendChild(h('span', null, h('b', null, 'Raportul tău, încărcat local'), ' · ', h('span', { translate: 'no' }, mine.name), ' · ' + Site.fmt.bytes(mine.size) + generated + '. Nu a părăsit acest browser.'));
    }
    els.title.textContent = shown === 'mine' && mine ? mine.name : 'raport.html';
    els.tag.hidden = shown !== 'demo';
  }

  /** Montează raportul `kind` ('mine' sau 'demo') în fereastră; întoarce true dacă a reușit. */
  function show(kind) {
    var api = root.EmagDashboard;
    var data = kind === 'mine' ? (mine && mine.data) : root.EMAG_DEMO_DATA;
    if (!api) { setStatus('error', 'Componenta raportului nu s-a încărcat (assets/dashboard.js lipsește).'); return false; }
    if (!data) { setStatus('error', kind === 'mine' ? 'Nu e încărcat niciun raport.' : 'Datele demonstrative nu s-au încărcat (assets/demo-data.js lipsește).'); return false; }
    unmountCurrent();
    shown = kind;
    els.mount.hidden = false;
    var failure = null;
    try {
      instance = api.mount(els.mount, data, { demo: kind === 'demo', headingLevel: REPORT_HEADING_LEVEL });
      // mount nu aruncă la o eroare de desenare: o raportează prin ok/errors (și își desenează singur o stare de eroare)
      if (instance && instance.ok === false) failure = (instance.errors && instance.errors.length) ? instance.errors.join(' ') : 'eroare necunoscută';
    } catch (error) {
      failure = error && error.message ? error.message : 'eroare necunoscută';
    }
    if (failure !== null) {
      shown = '';
      unmountCurrent();
      renderChrome();
      setStatus('error', 'Raportul n-a putut fi desenat: ' + failure + (/[.!?…]$/.test(failure) ? '' : '.'));
      return false;
    }
    renderChrome();
    els.scroll.scrollTop = 0;
    return true;
  }

  /** Eroare de încărcare: mesaj + eventual listă de detalii; raportul deja afișat rămâne neatins. */
  function fail(message, details, tail) {
    var h = Site.dom.h;
    var nodes = [message];
    if (details && details.length) {
      var list = h('ul', { class: 'status__list' });
      details.slice(0, MAX_ERRORS_SHOWN).forEach(function (d) { list.appendChild(h('li', null, d)); });
      if (details.length > MAX_ERRORS_SHOWN) list.appendChild(h('li', null, 'și încă ' + (details.length - MAX_ERRORS_SHOWN) + '…'));
      nodes.push(list);
    }
    if (tail) nodes.push(h('span', { class: 'status__tail' }, ' ' + tail));
    setStatus('error', nodes);
    return false;
  }

  /**
   * Validează textul unui analiza.json și, dacă e bun, îl afișează. Întoarce true dacă fișierul e acceptat. Sub DEFER_DRAW_BYTES
   * desenarea e imediată; peste, mesajul „Se desenează…” apare întâi, iar raportul se montează în cadrul următor.
   */
  function loadText(name, text, size) {
    var api = root.EmagDashboard;
    if (!text || !String(text).trim()) return fail('„' + name + '” e gol.', null, 'Alege analiza.json din folderul unei rulări.');
    var data;
    try {
      data = JSON.parse(text);
    } catch (error) {
      var hint = wrongFileHint(name);
      if (hint) return fail(hint);
      return fail('„' + name + '” nu e un JSON valid (detaliu tehnic: ' + (error && error.message ? error.message : 'necunoscut') + ').', null, 'Încarcă analiza.json așa cum l-a scris programul, fără să-l editezi.');
    }
    if (Array.isArray(data)) return fail('„' + name + '” conține o listă, nu un raport: seamănă cu comenzi.json sau retururi.json.', null, 'Încarcă analiza.json din același folder (sau refă raportul cu --din-cache).');
    if (!api) return fail('Componenta raportului nu s-a încărcat (assets/dashboard.js lipsește).');
    var verdict = api.validate(data);
    if (!verdict || !verdict.ok) {
      var errors = (verdict && verdict.errors && verdict.errors.length) ? verdict.errors : ['Fișierul nu are forma unui analiza.json.'];
      return fail('„' + name + '” nu e un analiza.json complet:', errors, 'Refă rularea cu ruleaza.bat și încearcă din nou.');
    }
    var token = ++drawToken;
    var draw = function () {
      if (token !== drawToken) return false;
      var previous = mine;
      mine = { name: name, size: size, data: data };
      if (!show('mine')) { mine = previous; renderChrome(); return false; } // un fișier care nu s-a putut desena nu înlocuiește raportul vechi
      setStatus('ok', 'am încărcat „' + name + '” (' + Site.fmt.bytes(size) + '). Datele rămân în browserul tău.');
      Site.state.navigate(STATE_TOKEN + '/' + SUB_MINE);
      return true;
    };
    if (size < DEFER_DRAW_BYTES) return draw();
    // Fișier mare: anunțăm „Se desenează…” și lăsăm browserul să-l picteze înainte de munca sincronă a componentei.
    setStatus('info', 'Se desenează raportul din „' + name + '” (' + Site.fmt.bytes(size) + ')…');
    root.requestAnimationFrame(function () { root.setTimeout(draw, 0); });
    return true;
  }

  /** Citește un fișier ca text (file.text() sau FileReader, după ce oferă browserul). */
  function readText(file) {
    if (typeof file.text === 'function') return file.text();
    return new Promise(function (resolve, reject) {
      var reader = new root.FileReader();
      reader.onload = function () { resolve(String(reader.result)); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsText(file);
    });
  }

  /** Procesează lista de fișiere primită (alegere sau tragere): doar primul se folosește. */
  function loadFiles(files) {
    if (!files || !files.length) return;
    var file = files[0];
    var extra = files.length > 1 ? ' (ai ales ' + files.length + ' fișiere; folosesc doar primul)' : '';
    if (file.size === 0) { fail('„' + file.name + '” e gol.', null, 'Alege analiza.json din folderul unei rulări.'); return; }
    if (file.size > MAX_BYTES) {
      fail('„' + file.name + '” are ' + Site.fmt.bytes(file.size) + ', peste limita de ' + Site.fmt.bytes(MAX_BYTES) + ' a acestei pagini.', null, 'Un analiza.json nu ar trebui să fie atât de mare: verifică dacă ai ales fișierul corect.');
      return;
    }
    setStatus('info', 'Se citește „' + file.name + '”…' + extra);
    readText(file).then(function (text) {
      if (loadText(file.name, text, file.size) && extra) Site.dom.announce('Am folosit doar primul fișier.');
    }, function () {
      fail('Browserul n-a putut citi „' + file.name + '”.', null, 'Încearcă din nou sau lipește conținutul fișierului mai jos.');
    });
  }

  /** Handler de adresă: #incarca/demo și #incarca/raportul-tau. */
  function onState(parsed, ctx) {
    if (parsed.sub === SUB_DEMO) { if (shown !== 'demo') show('demo'); }
    else if (parsed.sub === SUB_MINE) {
      if (mine) { if (shown !== 'mine') show('mine'); }
      else {
        Site.state.replace(STATE_TOKEN);
        setStatus('info', 'Nu e încărcat niciun raport în această sesiune. Alege analiza.json mai sus.');
      }
    }
    // la încărcarea paginii cu #incarca/<stare>, browserul nu găsește un element cu acest id: derulăm noi la secțiune
    var section = doc.getElementById(STATE_TOKEN);
    if (ctx && ctx.source === 'load' && parsed.sub && section) section.scrollIntoView();
  }

  /** Tragerea fișierelor: acceptă un fișier lăsat oriunde în pagină, ca browserul să nu îl deschidă în locul paginii. */
  function initDrop() {
    var depth = 0;
    var hasFiles = function (event) {
      var types = event.dataTransfer && event.dataTransfer.types;
      return !!types && Array.prototype.indexOf.call(types, 'Files') >= 0;
    };
    var setDragging = function (on) { doc.documentElement.classList.toggle('is-dragging', on); };
    root.addEventListener('dragenter', function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setDragging(true);
    });
    root.addEventListener('dragover', function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
    });
    root.addEventListener('dragleave', function (event) {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    });
    root.addEventListener('drop', function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      var section = doc.getElementById(STATE_TOKEN);
      if (section) section.scrollIntoView();
      loadFiles(event.dataTransfer.files);
    });
  }

  /** Pornește vizualizatorul: leagă input-ul, lipirea, butoanele de comutare și tragerea. */
  function init() {
    els.input = doc.getElementById('file-input');
    els.status = doc.getElementById('viewer-status');
    els.segMine = doc.getElementById('seg-mine');
    els.segDemo = doc.getElementById('seg-demo');
    els.banner = doc.getElementById('viewer-banner');
    els.title = doc.getElementById('viewer-title');
    els.tag = doc.getElementById('viewer-tag');
    els.empty = doc.getElementById('viewer-empty');
    els.mount = doc.getElementById('viewer-mount');
    els.scroll = doc.getElementById('viewer-scroll');
    var emptyDemo = doc.getElementById('viewer-empty-demo');
    var pasteInput = doc.getElementById('paste-input');
    var pasteLoad = doc.getElementById('paste-load');
    if (!els.input || !els.status || !els.segMine || !els.segDemo || !els.banner || !els.title || !els.tag || !els.empty || !els.mount || !els.scroll) return;

    els.input.addEventListener('change', function () {
      loadFiles(els.input.files);
      els.input.value = ''; // permite alegerea aceluiași fișier încă o dată
    });
    els.segDemo.addEventListener('click', function () { if (show('demo')) Site.state.navigate(STATE_TOKEN + '/' + SUB_DEMO); });
    els.segMine.addEventListener('click', function () {
      if (!mine) { setStatus('info', 'Încă n-ai încărcat un raport. Alege analiza.json mai sus.'); return; }
      if (show('mine')) Site.state.navigate(STATE_TOKEN + '/' + SUB_MINE);
    });
    if (emptyDemo) emptyDemo.addEventListener('click', function () { if (show('demo')) Site.state.navigate(STATE_TOKEN + '/' + SUB_DEMO); });
    if (pasteLoad && pasteInput) {
      pasteLoad.addEventListener('click', function () {
        var text = pasteInput.value;
        var size = new root.Blob([text]).size;
        // aceeași limită ca la fișier: un text de zeci de MB ar îngheța pagina la JSON.parse, fără niciun mesaj
        if (size > MAX_BYTES) {
          fail('Textul lipit are ' + Site.fmt.bytes(size) + ', peste limita de ' + Site.fmt.bytes(MAX_BYTES) + ' a acestei pagini.', null, 'Un analiza.json nu ar trebui să fie atât de mare: verifică dacă ai copiat fișierul corect.');
          return;
        }
        loadText('textul lipit', text, size);
      });
    }
    initDrop();
    renderChrome();
    Site.state.register(STATE_TOKEN, onState);
  }

  Site.viewer = { init: init, MAX_BYTES: MAX_BYTES };
})(window);

/* app-report.js — ecranul „Raportul tău”: aduce analiza.json de la aplicație și desenează raportul cu EmagDashboard.mount.
 * Primește: rularea de afișat (cea abia terminată sau una veche deschisă din listă), de la App.state. Dă înapoi, ca
 * window.App.report: init(), openPast(info). Raportul se desenează în #report-root cu aceeași componentă ca raportul generat
 * și ca site-ul (dashboard.js); titlurile blocurilor sunt h3, sub titlul h2 al ecranului. La ieșirea din ecran componenta se
 * dezmontează (își scoate ascultătorii). Numele din date intră doar prin textContent, în interiorul componentei.
 * Ce NU face: nu validează schema (o face EmagDashboard.validate, apelat de mount) și nu descarcă fișiere (app-download.js).
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});
  const HEADING_LEVEL = 3; // ecranul are h2 „Raportul tău”; blocurile raportului sunt h3
  const DEMO_NOTE = 'Rulare de probă, cu date inventate.';

  let mounted = null;
  let shownId = null;
  let requestSeq = 0; // un răspuns întârziat pentru o rulare părăsită între timp e ignorat

  /** Ce rulare arătăm acum: {id, kind, created, past}; null dacă ecranul nu are ce arăta. */
  function targetOf(snap) {
    if (snap.viewRun) return { id: snap.viewRun.id, kind: snap.viewRun.kind, created: snap.viewRun.created_at, past: true };
    if (!snap.server || !snap.server.run_id) return null;
    const startedHere = snap.runModeRunId === snap.server.run_id ? snap.runMode : null;
    return { id: snap.server.run_id, kind: startedHere, created: snap.server.started_at, past: false };
  }

  function setStatus(text, bad) {
    const status = App.dom.byId('report-status');
    status.className = 'status' + (bad ? ' is-bad' : '');
    status.textContent = text;
  }

  /** Titlul și subtitlul ecranului, potrivite rulării (veche sau nouă, reală sau cu date inventate). */
  function setHeading(target, kind, created) {
    const when = created ? App.format.dateTime(created) : '';
    App.dom.byId('done-t').textContent = target.past && when ? 'Raport din ' + when : 'Raportul tău';
    let sub = '';
    if (kind === 'demo') sub = DEMO_NOTE;
    else if (target.past) sub = 'Rulare veche, deschisă din lista de rulări anterioare.';
    else if (when) sub = 'Rulare din ' + when + '.';
    App.dom.byId('done-sub').textContent = sub;
    App.dom.byId('btn-again').textContent = target.past ? 'Înapoi la început' : 'Rulează din nou';
    App.screens.refreshTitle();
  }

  /** Scoate raportul din pagină și îl dezmontează. */
  function unmount() {
    requestSeq += 1;
    if (mounted) {
      mounted.unmount();
      mounted = null;
    }
    App.dom.clear(App.dom.byId('report-root'));
    shownId = null;
    setStatus('', false);
  }

  /** Aduce analiza și desenează raportul pentru `target`. */
  function show(target) {
    const seq = requestSeq + 1;
    requestSeq = seq;
    shownId = target.id;
    setHeading(target, target.kind, target.created);
    setStatus('Se încarcă raportul…', false);
    const info = target.kind ? Promise.resolve(null) : App.history.lookup(target.id);
    Promise.all([App.api.getAnalysis(target.id), info]).then(function (parts) {
      if (seq !== requestSeq) return;
      const data = parts[0];
      const known = parts[1];
      const kind = target.kind || (known && known.kind) || 'real';
      setHeading(target, kind, (known && known.created_at) || target.created);
      if (!root.EmagDashboard) {
        setStatus('Nu am putut încărca componenta raportului (dashboard.js). Reîncarcă pagina cu porneste.bat.', true);
        return;
      }
      mounted = root.EmagDashboard.mount(App.dom.byId('report-root'), data, { demo: kind === 'demo', headingLevel: HEADING_LEVEL });
      setStatus('', false);
    }).catch(function (error) {
      if (seq !== requestSeq) return;
      setStatus('Nu am putut încărca raportul: ' + (error && error.message ? error.message : 'eroare necunoscută') + '.', true);
    });
  }

  /** Deschide o rulare veche din lista de rulări anterioare. */
  function openPast(info) {
    App.state.openRun(info);
  }

  /** Leagă butonul „Rulează din nou” / „Înapoi la început” și se abonează la ecran. */
  function init() {
    App.dom.byId('btn-again').addEventListener('click', function () {
      if (App.state.get().viewRun) App.state.closeRun(); else App.state.dismiss();
    });
    App.state.subscribe(function (now) {
      if (now.screen !== 'done') {
        if (mounted || shownId !== null) unmount();
        return;
      }
      const target = targetOf(now);
      if (target && target.id !== shownId) show(target);
    });
  }

  App.report = { init: init, openPast: openPast };
})(window);

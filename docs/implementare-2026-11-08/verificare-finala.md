# Verificarea funcțiilor de cumpărături — 8 noiembrie 2026

Implementarea acoperă cele șase funcții aprobate și filtrarea Black Friday pe ore. Acceptanța automată pe contul real a trecut toate cele șase funcții; colectarea independentă Python și calculele sunt identice cu extensia. Conform E25, acesta este raportul de verificare înaintea commit-ului și push-ului autorizate de pe PC. Pachetul nu a fost publicat în magazin.

## Rezultate măsurate

| Verificare | Rezultat | Jurnal în `logs/functii-2026-11-08/` |
|---|---|---|
| Baseline înaintea editărilor | 795 unitare + 7 demo Edge | `_meta/baseline-unit.log`, `_meta/baseline-demo.log` |
| Unitare JS pe copia exactă a indexului Git, 1.1.0 | 845 trecute, 0 eșecuri | `_meta/release-unit.log` |
| Paritate completă JS/Python, 1.1.0 | 501 trecute, 0 eșecuri | `_meta/release-parity.log` |
| Suita completă extensie Edge, 1.1.0 | 112 trecute, 27 suite | `_meta/release-e2e.log` |
| Python complet | 4.845 trecute, 7 sărite, 1 referință documentară lipsă | `_meta/precommit-python.log` |
| Python după repararea referinței E25: decizii, gardă parole, demo și versiuni | 202 trecute, 0 eșecuri | `_meta/hours-python.log` |
| Python final: toate gărzile, decizii, demo și versiuni | 1.699 trecute, 0 eșecuri | `_meta/release-python.log` |
| Cele două probe anterior sărite din lipsa pip/distlib | 2 trecute după instalarea locală prin ensurepip | `_meta/installer-unskipped.log` |
| Build strict după orele BF | 106 fișiere, fără avertismente | `extensie/build/functii-2026-11-08/` |
| Timeout subproces cu descendent și coduri de ieșire | 2 trecute, ambele PID eliminate pe Windows | `extensie/tests/unit/acceptance_process.test.js` |
| Audit separat | 0 vulnerabilități demonstrate; 48 unitare + 4 Edge | `audit/_meta/`, `audit-securitate.md` |
| Audit reluat pentru ore și runner | 0 constatări deschise; 40 BF + 6 runner + 4 probe suplimentare | `audit/_meta/acceptance-final-unit.log`, `audit-securitate.md` |
| Acceptanță reală | 6/6 funcții trecute; colectare și analiză identice JS/Python | `iesiri/acceptanta/`, privat, ignorat de Git |
| Scanare întreg indexul Git | Gitleaks, 5,17 MB, 0 secrete | `_meta/gitleaks-release-index.log` |

În prima rulare Python, garda a prins două exemple URL cu credențiale interpretate drept adrese de e-mail. Testele construiesc acum aceleași URL-uri ostile prin proprietatea `username`; garda și validatorul nu au fost slăbite. Șase teste ale instalatorului desktop au picat deoarece mediul procesului Codex nu avea `PROCESSOR_ARCHITECTURE`; reluarea a citit valoarea AMD64 din mediul Machine al Windows și a transmis-o doar subprocesului. Nu s-au schimbat setări Windows sau codul instalatorului.

În rularea Python completă, singurul eșec a fost lipsa unei trimiteri către noua decizie E25; runnerul și ghidul o citează acum în contextul autorizării. Reluările afectate sunt verzi. Dintre cele 7 teste sărite inițial, două au trecut după instalarea pip 26.2.1 din distribuția Python în mediul local de test. Celelalte cinci țin de privilegii pentru legături simbolice și biți Unix; nu sunt declarate executate. Nu s-a repetat întreaga suită de 16 minute după modificarea documentară.

Parserul a trecut înaintea testelor. Nu există TypeScript sau un pas typecheck separat în pachet. Testele browser cer zero erori de consolă, încălcări CSP și cereri externe; diagnosticele native de închidere a browserului sunt separate de rularea paginii.

## Review de cod

Aplicate ponytail-review, thermo-nuclear-code-quality-review și verificarea datoriei shortcut pe codul schimbat și apelanți. Scara verificată: un utilizator local, mai multe pagini/panou deschise simultan, fără server de date.

Corecturi verificate: o singură atribuire a rambursărilor înainte de filtrarea perioadelor; demo fără linkuri spre retururi fictive; URL-uri canonice; anularea montărilor vechi; focusul după click/Enter și după închiderea formularului; etichete libere fără coliziune cu opțiunile interne; ștergere care nu poate fi anulată de un consumator vechi. Testele și probele prin mutație sunt descrise în rapoartele agenților. Nu au rămas constatări concrete de reparat în codul verificat. Niciun fișier de producție nu a trecut de 1.000 de linii; 0 comentarii shortcut noi.

Black Friday: început inclusiv, sfârșit exclusiv, fus Europe/Bucharest independent de Windows, refuz pentru ore DST ambigue/inexistente, ore lipsă excluse explicit, migrare schema 1 → 2 fără pierdere de preferințe și fără rescriere după ștergere. Un test separat verifică ora la milisecundă. Bugetele lunare/anuale păstrează selecția calendaristică.

Auditorul a prins un context Edge rămas deschis dacă workerul extensiei nu pornea; corecția a trecut aceeași probă care fusese roșie. Timeout-ul colectării Python oprește acum întregul arbore propriu de procese, iar folderul profilului este verificat înainte de ștergere.

## Pachet

- Folder: `extensie/build/functii-2026-11-08/`.
- Arhivă: `cheltuieli-emag-1.1.0.zip`; versiunea nouă a fost cerută explicit de Robert după confirmarea celor șase file în Chrome.
- SHA-256: `8da7f4c43778493b8efd19ae4756724a5947c87df87a2f06dc2b62493b11c185`.
- Acceptanța pe cont a folosit pachetul anterior bump-ului; cele 105 fișiere de aplicație sunt identice octet cu octet, iar manifestul diferă numai prin `version`. Build/testele pachetului au fost reluate pentru 1.1.0; nu s-a schimbat logica după testarea contului.
- Build-ul extras din indexul Git produce aceeași arhivă, octet cu octet, ca build-ul testat pe cont. `extensie/dist/` nu a fost înlocuit.
- Folderul instalat în Chrome, indicat de Robert prin captură, a primit cele 106 fișiere verificate prin hash; copia versiunii anterioare este în `logs/functii-2026-11-08/chrome-inainte/`. Robert a reîncărcat și a confirmat toate cele șase file. După bump este necesară încă o reîncărcare pentru eticheta 1.1.0, deoarece instrumentul de browser refuză accesul automat la pagina internă Chrome.

Capturile reale sunt în `docs/extensie/capturi/2026-11-08-implementare/`: raport înainte/după, Black Friday înainte/după introducerea orelor, cele cinci ecrane noi și panoul Chrome în ambele teme. Galeria autonomă este `galerie-implementare.html`; nu conține date din cont. Exporturile reale de acceptanță rămân separat în `iesiri/acceptanta/`.

## Limite și publicare

- Panoul nativ, stocarea Chrome și clicul care deschide un context SIDE_PANEL au fost probate în Edge. Proba reală ulterioară a verificat oferta principală live, comparația cu istoricul și salvarea țintei. Black Friday a fost verificat printr-un oracol independent, bugetele lunar/anual și etichetele prin salvare/reîncărcare, retururile prin numărare/linkuri, iar PNG-urile prin egalitate exactă cu previzualizarea și ascunderea sumei. Preferințele de probă au fost restaurate; copia profilului a fost ștearsă după paritatea completă. Rezultatele reale și exporturile rămân locale, fără identificatori sau produse în acest raport public.
- Firefox: 8/8 combinații funcționale, 40 scanări axe fără violations/incomplete. WebKit: 8/8 funcționale și 40 scanări axe curate, dar 8 eșecuri la poarta CSP din cauza widgetului nativ select, confirmate prin probă minimă; nu este declarat complet verde. Panoul Edge are încă 8 scanări axe curate. Detalii și capturi în `ui-motoare.md`; alte motoare nu înlocuiesc API-urile Chrome native.
- Politica și formularul de magazin au un addendum propus în `docs/aprobare-confidentialitate-2026-11-08.md`; aprobarea lui este necesară înaintea publicării. Niciun furnizor nou sau cost introdus.
- Scanerele Semgrep, Gitleaks și npm audit nu au găsit probleme. OSV nu era instalat; nu este declarat rulat.
- Un singur commit include și modificările staged existente; E25 autorizează push-ul de pe PC. Verificarea rulărilor CI urmează după push; acest raport nu pretinde un rezultat CI încă neobservat. Runnerul nu modifică comenzile/retururile și nu trimite preferințele la eMAG.

## Corecția testului după primul push

Commit-ul inițial `83a4fbf` a fost împins de pe PC, cu remote identic. Robert a confirmat ulterior versiunea 1.1.0 activă în Chrome. CodeQL și verificarea dependențelor au trecut; joburile de descărcare uv/Gitleaks au primit HTTP 504, inclusiv la o reluare. Scanarea locală Gitleaks a tuturor celor 30 de commit-uri și a arborelui staged nu a găsit secrete.

CI Chromium a trecut 110 din 112 teste; cele două eșecuri proveneau din aceeași sondă la `sidepanel.test.js`: după clicul de reîncărcare, predicatul citea butonul din documentul tranzitoriu, unde elementul nu exista încă, și producea TypeError plus eșecul gărzii de consolă. Testul instalează acum așteptarea navigării înainte de clic, așteaptă DOMContentLoaded, apoi verifică explicit același text și ascunderea produsului. Nu există sleep, allowlist sau excepție care să ascundă o eroare.

Verificare locală a corecției: parser trecut, trei probe izolate ale panoului (30/30), apoi suita completă Edge (112/112), fără erori de consolă/CSP/rețea. Jurnale: `_meta/ci-panou-fix*.log` și `_meta/ci-fix-full-e2e.log`. Producția și hash-ul ZIP 1.1.0 sunt neschimbate. Robert a autorizat explicit un al doilea commit/push pentru această corecție; starea finală CI se verifică pe acel commit, fără a declara anticipat succesul.

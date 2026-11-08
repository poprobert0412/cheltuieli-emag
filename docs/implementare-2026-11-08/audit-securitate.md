# Audit de securitate — emag_cheltuieli, funcțiile extensiei — 2026-11-08

## Rezumat

Audit încheiat pe codul inițial, Black Friday pe ore/schema 2 și runnerul de acceptanță; raportul este singurul document editat de auditor.
Verdict: 0 constatări deschise — 0 critice, 0 mari, 0 medii, 0 mici; 1 mică de mediu de dezvoltare găsită și remediată (DEV-1).
Inițial: 48/48 unitare + 4/4 Edge și build strict trecute. Reluare: 40/40 unitare BF + 6/6 runner și 4/4 probe suplimentare verzi.
Auditorul nu a folosit cont real, profil personal, cookie-uri sau cereri către producție; acceptanța reală este executată separat de coordonator.
Fără modificări de cod, commit sau push de către auditor.

## Constatări

| ID | Regula (securitate-web.md) | Fișier:linie | Dovadă | Severitate | Remediere într-un rând |
|---|---|---|---|---|---|

Nicio constatare deschisă. DEV-1, identificată în runnerul local și remediată de coordonator, este documentată cu test roșu → verde în addendumul de mai jos. Nu s-a identificat o cale prin care o pagină externă neautorizată să citească istoricul, să aleagă o destinație arbitrară de rețea sau să execute textul produselor/etichetelor în extensie.

## Verificat, fără probleme

- Randare prin textContent/createTextNode; fără interpretarea numelor, etichetelor și produsului citit ca HTML.
- Schema închisă refuză câmpuri necunoscute, obiecte cu prototip neobișnuit și cheile __proto__/constructor/prototype; sumele introduse sunt bani întregi, safe-integer, nenegativi/null, iar textele exclud control/bidi.
- Destinații limitate la produse HTTPS www.emag.ro; fără credențiale/port și fără rețea nouă în panou.
- Citire prin scripting în lumea izolată doar după acțiune; identitatea și fila activă sunt recitite după extragere. Navigarea nu citește automat produsul următor. Mesajul pentru raport cere URL-ul exact al panoului și ID-ul extensiei.
- CSP în ambele pagini: script-src 'self', default-src 'none', connect-src 'none', base-uri 'none', form-action 'none'; fără scripturi inline noi sau resurse externe în HTML.
- AES-GCM autentificat, cheie locală neexportabilă și scriere read-modify-write sub un Web Lock comun.
- Invalidarea scriitorilor după ștergere, inclusiv înaintea primei salvări; actualizări concurente între contexte.
- Ciphertextul corupt și cota plină nu devin salvare reușită sau stare goală; rezultatele vechi ale citirii nu sunt reaplicate după invalidare/dispose.
- Demo exclusiv în memorie; PNG construit din câmpuri agregate, fără identificatori/nume de produse.
- Comparația păstrează denumirea integrală, fără subșir/fuzzy; prețul unitar provine din kept_paid_bani/kept_qty, după reducerile motorului și fără transport. Retururile sunt atribuite o dată înaintea filtrării perioadelor; intervalul Black Friday vine din config/black-friday.json și rămâne editabil.
- Build-ul copiază surse/config publice explicite și demo-ul generatorului existent; nu include config/categorii.personal.json, profilul browserului, ieșiri sau jurnale. .gitignore acoperă .env/.env.*, profilul, ieșirile și jurnalele; nu s-a găsit .env în zona proiectului inspectată, excluzând profilul personal și mediile de unelte.
- Recitită modificarea finală de focus în ui_dom.js/shopping_app.js: dataset este comparat ca text în JS, fără selector ori HTML interpolat din date.

## Scanere

- Node v24.14.0: 48/48 teste unitare relevante, zero eșecuri/sărite; jurnal logs/functii-2026-11-08/audit/_meta/unit.log.
- Node v24.14.0: parser pentru 24 module JS/MJS, zero erori; build --strict, 105 fișiere, jurnal _meta/build.log, artefact separat logs/functii-2026-11-08/audit-dist.
- Edge instalat/Playwright-core 1.63.0, shopping_data.test.js pe artefactul auditorului: 4/4 trecute, zero erori de consolă/CSP/rețea externă; jurnal _meta/shopping-data-e2e.log. Profilul temporar a fost închis de harness; niciun server pornit.
- npm 11.11.0, audit --omit=dev și audit incluzând dev: zero vulnerabilități; jurnale _meta/npm-audit.json și _meta/npm-audit-all.json. Extensia are doar dependențe dev.
- Gitleaks 8.30.1, dir extensie/src cu regulile proiectului și --redact: zero rezultate; jurnal _meta/gitleaks-src.log.
- Gitleaks 8.30.1, artefactul construit și git scoped extensie/src + build + manifest (1 commit): zero rezultate; jurnale _meta/gitleaks-dist.log și _meta/gitleaks-git.log.
- Semgrep 1.184.0, p/owasp-top-ten + p/secrets, 26 fișiere/104 reguli: zero rezultate, ~100% linii parsate; jurnal _meta/semgrep.log.
- osv-scanner lipsește din PATH; nerulat. Instalare posibilă: go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest, apoi osv-scanner scan -L extensie/package-lock.json. Auditul npm a acoperit lockfile-ul existent, inclusiv cele două pachete dev.
- Bandit/pip-audit, scanere Docker/shell/CI: în afara acestui audit limitat la funcțiile extensiei JS, nu s-au schimbat backend, SQL, Supabase, plăți, mobil, LLM, containere sau workflow-uri în scopul primit. Nu sunt declarate verificate.

## Nu s-a putut verifica

- Forma live a paginii eMAG: fără probe noi către producție în acest audit; proba publică anterioară a primit HTTP410.
- Politica și formularul magazinului: addendumul din docs/aprobare-confidentialitate-2026-11-08.md este propus, publicarea rămâne neautorizată; decizie Robert înaintea distribuirii. Politica veche și FAQ-ul descriu încă numai analiza/jurnalul: listă/bugete/etichete/citire produs/PNG trebuie incluse înaintea lansării, conform porții deja documentate; nu există aici o lansare efectuată sau o scurgere demonstrată.
- Integrarea completă, paritatea Python și testele UI/native sidePanel sunt rulate de coordonator; auditorul a citit implementarea și testele, dar nu le declară verificate independent prin propria execuție. Execuțiile proprii ulterioare sunt detaliate în addendum; nu includ acceptanța pe cont real.
- Compatibilitatea cu alte versiuni Chromium, magazinul Chrome, setările conturilor și regulile Windows de firewall nu au fost probate; niciun server local sau regulă de firewall nu a fost creat(ă)/modificat(ă) în această etapă.
- Criptarea locală nu protejează împotriva controlului întregului profil/browser sau accesului la extensia deja deschisă; limita există și în politica aprobată. Nu s-au deschis date personale reale.

Urme: raportul, jurnalele și artefactul auditorului menționate mai sus; Semgrep a fost instalat de uvx în cache-ul uneltelor, în afara codului proiectului. Nu s-au făcut reparații, capturi, modificări de cod, commit sau push. GATA.

## Addendum — Black Friday pe ore și schema 2

Reluat la cererea explicită a lui Robert. Audit defensiv în citire pentru campaign_time.js, shopping_schema.js, shopping_store.js, shopping_period.js, shopping_insights.js, campaign_view.js, shopping.css și config/black-friday.json. Configurația aprobată este 6 noiembrie 2026, 07:15 → 7 noiembrie 2026, 00:00, Europe/Bucharest. Au fost recitite după freeze și cont_real.mjs, shopping_acceptance.mjs, acceptance_process.mjs și testele lor; addendumul este final pe acest scop.

**Constatări noi: 0 demonstrate.** Verificat:

- campaign_time.js:18/38/43/44/48 — format HH:MM strict, fus unic, refuz explicit pentru ore locale DST inexistente/ambigue și pentru sfârșit ≤ început. Timestamps cu offset sunt convertite în instanțe; cele naive sunt interpretate în Europe/Bucharest, fără fusul calculatorului.
- shopping_schema.js:47/49/51/91 — schema 1 este permisă explicit numai la granița de migrare; schema 2 păstrează validarea închisă, protecția cheilor/prototipurilor, URL-urilor și banilor. Migrarea conservă lista, bugetele, etichetele și datele calendaristice; intervalele incompatibile primesc ore null/null și cer completare, fără total financiar inventat.
- shopping_store.js:19/45/46/60/65 — migrarea și actualizarea lucrează pe cea mai recentă stare sub Web Lock-ul comun și folosesc generația capturată. O citire inițială veche nu poate suprascrie actualizarea altui context; cota plină păstrează înregistrarea veche.
- shopping_period.js:38/44/47 — campania folosește început inclusiv și sfârșit exclusiv; comenzile fără oră sigură sunt excluse și numărate. Lipsa datelor brute/orelor produce indisponibilitate și paid:null. Calea zilnică existentă rămâne separată; agregarea reutilizează alocările motorului.
- campaign_view.js:41/88/93/98 — aceleași validări ajung la store, rezultatele folosesc insights.campaign; mesajele sunt text și execuția întârziată verifică active(). Fără destinații noi de rețea sau operații de cont.

**Verificări executate de auditor:** parser 10/10 module/teste JS; 40/40 teste campaign_time + shopping_store + shopping_insights + saved_analysis_watch + criptare. Jurnal: logs/functii-2026-11-08/audit/_meta/bf-ore-unit.log.

Suplimentar, două teste node:test cu fixture-uri inventate, executate din stdin, au trecut: ștergere exact după citirea schemei 1 și înaintea commitului de migrare (citirea și scrierea veche sunt refuzate, stocarea rămâne goală); tipuri/ore/offseturi malformate și precizia la milisecundă. Jurnal: _meta/bf-ore-edgecases.log. Nu s-a scris cod de test în proiect și nu s-a accesat Chrome, vreun profil sau cookie.

**Limite:** nu s-a executat acceptanța pe cont real în acest audit; aceasta rulează separat la coordonator. Testele UI noi au fost citite, fără execuție independentă în browser în această reluare. Scanarea întregului repo nu a fost repetată; dependențele și suprafețele de rețea nu s-au schimbat în acest lot.

Runnerul final verifică toate cele șase funcții și cere fiecare status passed plus paritate nouă pentru cod 0 (cont_real.mjs:161); blocked/failed nu devin succes. Folosește un director nou de referință Python, jurnale private și numai coduri/numărători în stdout. Copia profilului are verificare de cale înainte de ștergere; scriptul nu citește cookie-uri prin API și nu publică rezultate. Modulul shopping_acceptance.mjs validează URL-ul produsului înainte de navigare (245/246), nu face capturi, exportă PNG-ul local în iesiri/ ignorat de git și restaurează preferințele în finally; eșecul restaurării rămâne eroare (323/326). Rezultatele sunt scrise pe parcurs. Nu s-au găsit secrete ori date personale înscrise în codul runnerului.

Parserul shopping_acceptance.mjs și al testului său a trecut. shopping_acceptance.test.js + acceptance_process.test.js: 6/6 trecute independent de auditor, fără browser/profil, inclusiv oracol separat pentru ore/offset/DST și oprirea proceselor Node inventate. Jurnal: _meta/acceptance-final-unit.log.

### Runner local — constatare remediată

La primul freeze al cont_real.mjs s-a confirmat o problemă mică, de **mediu de dezvoltare**: contextul pornit nu era închis când waitForEvent('serviceworker') arunca. Închiderea din runAcceptance era instalată abia după întoarcerea launchWithExtension. O pagină externă nu poate apela acest runner; cazul cere executarea locală autorizată și un eșec la pornire. Expune accidental durata de viață a copiei profilului autentificat/browserului de probă, fără a fi demonstrată exfiltrarea sau accesul la alte conturi.

| ID | Regula | Fișier:linie (primul freeze) | Dovadă (max. 2 rânduri) | Severitate | Remediere |
|---|---|---|---|---|---|
| DEV-1 | securitate-web.md — servere/mediu local; ci-cd.md — oprirea proceselor proprii | extensie/scripts/cont_real.mjs:107,127 | `if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: WORKER_TIMEOUT_MS });`<br>`const { context, extensionId } = await launchWithExtension(profileDir, EXTENSION_DIST);` | mică, mediu de dezvoltare | Închide contextul în launchWithExtension la eroare înainte de a retransmite excepția; apoi șterge profilul. |

Dovadă executată: node:test cu funcția reală extrasă în VM și API Chromium fals. waitForEvent aruncă; close era apelat de 0 ori, deși testul cere 1. Test roșu inițial, ieșire 1: logs/functii-2026-11-08/audit/_meta/acceptance-worker-cleanup-red.log. Nu a fost pornit vreun browser sau deschis vreun profil.

**DEV-1 închis după re-freeze:** cont_real.mjs închide acum contextul în catch-ul launchWithExtension, înainte de rethrow. Exact aceeași probă cere și obține close=1. Noul acceptance_process.mjs oprește arborele la timeout; unitarele reale pe procese Node inventate confirmă dispariția ambelor PID (părinte și copil). Ramura cu taskkill eșuat a fost simulată: respinge acceptance_process_cleanup_failed, închide descriptorul jurnalului și nu se transformă în succes când procesul emite ulterior close(0). Toate cele 4 probe sunt verzi; jurnale _meta/acceptance-cleanup-green.log și _meta/acceptance-process-unit.log. Parserul celor 3 fișiere noi/actualizate a trecut. Ramura POSIX nu a fost executată pe acest Windows; nu se declară verificată.

GATA. Niciun proces/browser/server al auditorului rămas; codul este nemodificat de auditor. Au rămas raportul și jurnalele de verificare menționate.

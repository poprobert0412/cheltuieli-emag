# Panou Chrome — progres

1. Reguli și machetă: citite; nicio regulă locală AGENTS.md/CLAUDE.md găsită. Ownership: `extensie/src/panou/**`, `sidepanel.html`, `background.js`, cele patru teste dedicate.
2. Implementat: URL strict www.emag.ro HTTPS `/slug/pd/COD`, extractor autonom în lume izolată, ofertă unică RON, JSON-LD legat de titlul complet și canonical; fallback meta explicit, fără căutare globală de cifre.
3. Implementat: comparație integrală după nume, păstrează variantele, preț unitar din registru, minim și ultima zi (ultima valoare necunoscută când ziua conține prețuri diferite).
4. Implementat: panou nou pe app.css/app-theme, CSP fără inline, țintă în store criptat, invalidare la navigare/ștergere, fără recitire automată a paginii următoare.
5. Implementat: iconița deschide sidePanel înainte de primul await și transmite autorizare unică în storage.session; alte pagini păstrează aplicația. Cererea raportului acceptată numai din sidepanel.html al aceleiași extensii.
6. Verificat: parser JS și 14 teste unitare verzi; log `logs/functii-2026-11-08/_meta/panou-unit.log`. Două mutații pe copii (ofertă multiplă acceptată și potrivire de prefix) au fost detectate: `panou-mutation.log`.
7. Verificat: build strict și 10 teste e2e Edge verzi, inclusiv registrul real cu reduceri, URL de variantă diferită, actualizare țintă fără duplicat, criptare, sumă invalidă, tema după reload, corupție, navigare, ștergere/reload și raportul complet. Loguri `panou-build.log`, `panou-e2e.log`; build `logs/functii-2026-11-08/panou-dist`.
8. Verificat: API nativ `chrome.sidePanel.open` din clic de browser și context real `SIDE_PANEL` cu documentul sidepanel.html în Edge instalat. Butonul API de probă există numai în DOM-ul harness-ului; nu în codul livrat.
9. Capturi reale: `docs/extensie/capturi/2026-11-08-implementare/panou-chrome-400-comparatie-light.png`, `-dark.png`, `panou-chrome-320-light.png`, `-dark.png`; teme aplicate prin butonul real, date inventate, trimise coordonatorului imediat. Ecran nou fără panou anterior instalabil.
10. NEVERIFICAT live: profil Edge nou fără cont primește HTTP410 pe homepage și produs public din PDF oficial eMAG; lipsesc h1 și JSON-LD, extractorul refuză ambiguitatea. Web reader primește 511. Log `panou-public-product.log`; nicio relaxare de selector/preț făcută. Forma reală JSON-LD a produsului rămâne de verificat dintr-o pagină accesibilă.
11. După ștergere store-ul rămâne invalidat: mesajul și butonul sunt «Reîncarcă panoul», iar clicul reîncarcă documentul și creează consumator nou, fără reactivarea scrierilor vechi. Testat cap-coadă.
12. Review pe fișierele proprii: citire completă și criteriile verifica-cod/Ponytail/thermo; fără constatări deschise și fără marcaje shortcut noi. Auditorul coordonat de root rămâne poarta comună.

Nu s-a făcut commit/push și nu s-au pornit servere.

## Runner de acceptanță separat

- `extensie/scripts/shopping_acceptance.mjs` exportă `verifyShoppingAcceptance({context,page,extensionId,outFolder,entry,productUrl?})`; nu pornește browser, login, profil sau colectare.
- Oracolul BF filtrează independent instanțele precise în fusul configurat și compară număr/sume cu alocările motorului complet, fără presupuneri despre numărul comenzilor.
- Cele șase funcții sunt verificate prin UI pe entry-ul furnizat; bugetele de probă derivă din analiză, eticheta este inventată, iar lista folosește numai produsul live din argument. Produs lipsă/HTTP indisponibil/extractor ori preț necunoscut rămâne blocked.
- Preferințele originale sunt restaurate și verificate în finally; dacă inițial cheia lipsea, cheia creată este eliminată. Eșecul restaurării aruncă eroare.
- Numai verdicte/numărători și coduri fixe ajung în `outFolder/cumpărături/verdicturi.json`, actualizat după fiecare funcție. Cele două PNG rămân în același folder privat; nu se fac screenshots.
- Verificări: parser, 4/4 teste unitare oracol, runner complet în Edge pe fixture-uri exclusiv inventate: toate șase passed; a doua trecere fără produs a confirmat blocked și restaurarea exactă a preferințelor existente. Zero console/CSP/rețea neprevăzută. Loguri `_meta/shopping-acceptance-unit.log`, `_meta/shopping-acceptance-fake.log`.
- Proba inițială a descoperit fixture HTML fără charset, care genera caractere de control în nume; s-a corectat numai fixture-ul privat. Build-ul final de probă este curat, fără instrumentarea de diagnostic.
- Nu s-a rulat acceptanța pe cont real de către agent; această etapă rămâne coordonatorului. `cont_real.mjs` nu a fost modificat de agent.

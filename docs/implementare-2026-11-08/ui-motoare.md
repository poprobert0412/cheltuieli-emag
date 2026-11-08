# Suprafețe web — WebKit și Firefox

Verificarea folosește modulele reale din build-ul propriu `logs/functii-2026-11-08/ui-dist`, datele demo generate și `mountShoppingApp(..., demo:true)`. Harnessul și serverul există numai în test; producția nu primește mock-uri Chrome sau modificări CSP.

## Mediu și limite

- WebKit 26.6: executabilul instalat `LOCALAPPDATA/ms-playwright/webkit-2370/Playwright.exe`.
- Firefox 159.0.1 instalat: canalul `moz-firefox`, protocol WebDriver BiDi.
- 1440, 1024 (tabletă), 390 și 320 px; ambele teme. WebKit are și atingere la lățimile de telefon; Firefox BiDi verifică dimensiunea ferestrei, fără a pretinde emulare tactilă.
- API-urile extensiei, sidepanel și storage real rămân verificate numai în Edge; acestea nu sunt simulate aici.
- Scanner: axe-core 4.14.0 instalat exclusiv în `logs/functii-2026-11-08/browser-tools`; dependențele proiectului sunt neschimbate.
- Server static numai pe `127.0.0.1`, cu căi exacte și CSP strict; `/.env`, majuscule incorecte și fluxuri NTFS refuzate cu 404. Fiecare rulare închide serverul și browserele în finalizare.

## Diagnostice confirmate

1. **WebKit, CSP nativ:** o probă minimă fără click, captură sau axe creează și atașează un `<select>` gol; motorul emite `style-src-attr`. Aceeași probă cu button, input text/date/checkbox și progress nu emite încălcări. Nu este un stil inline scris de aplicație. Jurnal: `_meta/ui-webkit-native-proba.log`.
2. **Firefox, captură Playwright:** utilitarul de captură injectează regula goală `body {}` pentru sincronizare, indiferent de `caret:initial`/`animations:allow` (`playwright-core/lib/coreBundle.js`, funcțiile `inPagePrepareForScreenshots` și `_preparePageForScreenshot`). SHA-256 al regulii este `YjaKGiklmzC6wjXA513HAMmzus8VE61XCOT+SmwNZWA=`, identic cu diagnosticul CSP. Proba numerică și prima rulare sunt păstrate în jurnale. Capturile sunt fază separată, cu toate diagnosticele raportate; nu există allowlist în aserțiuni și CSP-ul rămâne neschimbat.
3. **Focus nativ WebKit:** clicul pe buton poate lăsa focusul în afara formularului. Testul respectă starea nativă și verifică separat salvarea prin Enter cu restaurare pe fila activă când editorul se închide.

## Rezultate

| Motor | Combinații | Controale/focus/lună/PNG | Layout 5 ecrane × 4 lățimi × 2 teme | Axe | Poarta zero erori/CSP |
|---|---:|---|---|---|---|
| Firefox 159.0.1 | 8 | 8/8 trecute | 40/40, fără overflow | 40 scanări, 0 violations, 0 incomplete | 8/8 trecute înainte de capturi |
| WebKit 26.6 | 8 | 8/8 trecute | 40/40, fără overflow | 40 scanări, 0 violations, 0 incomplete raportate de scanner | 8/8 eșuate din cauza widgetului nativ select sub CSP; nu sunt declarate verzi |

Node test runner: 17 teste, 9 trecute (8 Firefox + proba nativă), 8 eșuate (WebKit strict CSP), 66,3 secunde. Nu există excepții/allowlist pentru a transforma aceste eșecuri în succes. În WebKit, 20 de diagnostice native apar în faza interacțiunilor și alte 4 la rerandările necesare fazei scanner, pe fiecare combinație; lipsa violations/incomplete în axe nu înlocuiește poarta CSP eșuată.

Capturile sunt fază separată: 20 de imagini în `docs/extensie/capturi/2026-11-08-implementare/plansa-webkit-firefox.png`. Toate cele 28 de diagnostice apărute în această fază sunt păstrate în `capture_issues`, fără filtrare. Dintre ele, Firefox are 10 mesaje produse de sincronizarea capturii descrisă mai sus; WebKit are și rerandări ale widgetului nativ. Acestea nu sunt atribuite aplicației sau scannerului.

Serverul ultimei rulări (`127.0.0.1:8461`) și browserele au fost închise înainte de raport. Datele detaliate: `logs/functii-2026-11-08/_meta/ui-motoare.json`; ieșirea completă: `_meta/ui-motoare.log`. Nu s-a modificat selectul, CSP-ul sau alt cod de producție pentru această probă. Neverificat pe Safari/iOS real.

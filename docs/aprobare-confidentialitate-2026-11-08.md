# Addendum propus — cumpărături și panou Chrome

8 noiembrie 2026. Textele de mai jos sunt pregătite pentru aprobarea înaintea publicării noilor funcții. Politica aprobată anterior rămâne în `CONFIDENTIALITATE-EXTENSIE.md`; acest document nu afirmă o aprobare nouă. **Aprobat de Robert pe 10 noiembrie 2026 (E26)** și integrat în politică și în `MAGAZIN-EXTENSIE.md`.

## Politica: completări exacte

**1. Citirea produsului.** „Când deschizi panoul din iconița extensiei pe o pagină de produs sau apeși «Citește produsul», extensia citește denumirea, adresa și prețul disponibil al produsului principal. Le compară local cu cumpărăturile tale. Nu monitorizează automat alte pagini sau prețuri.”

Temei: transparența prelucrării cerută de Chrome Web Store, inclusiv pentru date procesate exclusiv local. Verificat la 08.11.2026: `extensie/src/background.js` (`handleActionClick`), `panou/active_product.js`, `panou/product_page.js`, `panou/sidepanel.js` (`readProduct`). Starea: implementat local.

**2. Datele salvate.** „La cererea ta, extensia păstrează în browser lista de produse, adresele și prețurile observate, prețurile-țintă, bugetele, perioada aleasă și etichetele personale. Aceste date sunt criptate local împreună cu analiza și jurnalul, rămân până le modifici sau le ștergi și nu sunt trimise autorului. O analiză nouă păstrează lista și preferințele.”

Temei: informarea privind categoriile, scopul și retenția datelor. Verificat la 08.11.2026: `cumparaturi/shopping_schema.js`, `shopping_store.js`, `stocare/private_storage.js`; testele `shopping_store.test.js` și `shopping_data.test.js` verifică criptarea, persistența și concurența. Starea: implementat local.

**3. Ștergere.** „«Șterge datele» elimină analiza, jurnalul, lista de produse, bugetele, etichetele și cheia locală. Datele afișate în celelalte pagini ale extensiei sunt invalidate. Fișierele descărcate anterior se șterg separat.”

Temei: informarea corectă privind ștergerea. Verificat la 08.11.2026: `stocare/private_storage.js` (`clear`), `ecrane/saved_analysis_watch.js`, `cumparaturi/shopping_store.js`, testele între două pagini. Starea: implementat local.

**4. Exportul imaginii.** „Poți descărca local bilanțul anual ca imagine PNG necriptată. Imaginea conține anul și totalurile previzualizate, fără numere de comandă sau denumiri de produse; suma poate fi ascunsă înainte de descărcare. Extensia nu publică imaginea.”

Temei: informarea privind exportul și divulgarea controlată de utilizator. Verificat la 08.11.2026: `cumparaturi/recap_export.js` (`recapData`, `downloadRecap`) și `recap_view.js`; testul browser verifică imaginea exportată și ascunderea sumei. Starea: implementat local.

Sursă oficială citită la 08.11.2026: [Chrome Web Store — User Data FAQ, întrebările 3, 7, 12 și 14](https://developer.chrome.com/docs/webstore/program-policies/user-data-faq). Nu se adaugă furnizori sau transferuri externe.

## Câmpurile din magazin: propuneri gata de lipit

**Scop unic:** “Help users understand and plan their own eMAG spending, with local purchase reports, budgets, return follow-up, personal labels, a wishlist and a product-page comparison against their own purchase history.”

**Permisiunea sidePanel:** “Displays the user's personal product comparison and target-price controls in Chrome's side panel while they view an eMAG product. The panel opens on the user's action and does not read other websites.”

**Completare scripting:** “On the user's action, also reads the main product name, URL and available price from the active eMAG product page in the isolated world. It does not change the merchant page or execute remote code.”

**Completare storage:** “Also stores the user's wishlist, observed and target prices, budgets, campaign dates and personal labels locally, encrypted. These preferences survive a new analysis and are removed by Delete data.”

Formularul de date trebuie să declare și conținutul introdus de utilizator (lista și etichetele), adresa paginii de produs și prețurile/bugetele. Declarațiile financiare și conținutul site-ului existente se păstrează. Etichetele exacte ale formularului se verifică în dashboard la publicare; nu s-a accesat sau modificat contul magazinului în această sesiune.

## Condiții înainte de publicare

- Aprobarea acestor texte, apoi înlocuirea afirmațiilor vechi „numai raportul” și „două permisiuni” din politica și formularul public.
- Citirea pe o pagină de produs eMAG reală a trecut ulterior în acceptanța autorizată din 08.11.2026, inclusiv comparația și salvarea țintei; proba publică veche HTTP 410 nu mai este un blocaj al acestei verificări.
- O versiune nouă pentru lansare, pachetul verificat și acordul explicit de publicare în magazin; E25 autorizează separat commit-ul și push-ul de pe PC după acceptanță, fără a echivala cu trimiterea în Chrome Web Store.

## Descrierea lungă 1.1.0 — APROBAT de Robert pe 10 noiembrie 2026 (E27)

Descrierea aprobată în E20 (`MAGAZIN-EXTENSIE.md` §3) rămâne neschimbată, cu excepția schimbărilor numerotate de mai jos. Temei: descrierea din magazin nu trebuie să contrazică politica și formularul de date (politica Chrome Web Store privind metadatele și User Data FAQ); cele două paragrafe despre date ar fi devenit incomplete după E26.

1. În „CE ÎȚI ARATĂ”, după rândul cu exporturile, se adaugă:
   - „Planificarea campaniilor, ca Black Friday: perioada cu date și ore, lista de produse cu prețuri-țintă și bilanțul comenzilor din acel interval.”
   - „Bugete lunare sau anuale, comparate cu ce ai plătit efectiv.”
   - „Retururile fără rezultat sau fără rambursare, de urmărit.”
   - „Etichete personale pentru cumpărături și bilanțul anului ca imagine PNG, cu suma ascunsă dacă vrei.”
   - „Pe pagina unui produs eMAG, în panoul lateral Chrome: cât ai plătit ultima dată și minimul tău pentru același produs.”
2. În „DATELE TALE”, după fraza „Extensia citește paginile comenzilor și retururilor în memorie, apoi păstrează câmpurile necesare raportului.” se adaugă: „Pe o pagină de produs, doar la cererea ta, citește denumirea, adresa și prețul produsului principal.”
3. Fraza „Ultima analiză și jurnalul sunt păstrate criptat în profilul browserului.” devine: „Ultima analiză, jurnalul, lista de produse, bugetele și etichetele sunt păstrate criptat în profilul browserului.”
4. Fraza „«Șterge datele» elimină analiza, jurnalul și cheia locală.” devine: „«Șterge datele» elimină analiza, jurnalul, lista de produse, bugetele, etichetele și cheia locală.”
5. Fraza „Fișierele descărcate sunt necriptate și trebuie șterse separat.” devine: „Fișierele descărcate, inclusiv imaginea bilanțului, sunt necriptate și trebuie șterse separat.”

Verificat la 10.11.2026: `docs/FUNCTII-CUMPARATURI.md` („Folosire”, „Date și limite”), `extensie/src/panou/sidepanel.js` (`readProduct`, `refreshHistory`), `extensie/src/aplicatie.html:210`. Starea: aprobat („Da, toate 1–11”), integrat în `MAGAZIN-EXTENSIE.md` §3; se arată în ciorna din dashboard înainte de trimitere.

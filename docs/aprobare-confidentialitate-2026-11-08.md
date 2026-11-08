# Addendum propus — cumpărături și panou Chrome

8 noiembrie 2026. Textele de mai jos sunt pregătite pentru aprobarea înaintea publicării noilor funcții. Politica aprobată anterior rămâne în `CONFIDENTIALITATE-EXTENSIE.md`; acest document nu afirmă o aprobare nouă.

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

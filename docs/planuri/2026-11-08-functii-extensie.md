# Cele șase funcții aprobate — 8 noiembrie 2026

Robert a aprobat toate cele șase machete din `docs/extensie/capturi/2026-11-08-idei/`, inclusiv textele și aspectul, și implementarea lor. A cerut atenție la design și adaptarea Black Friday la evenimentul tocmai încheiat. A aprobat 3 implementatori simultan și 1 auditor ulterior; coordonatorul integrează și verifică.

## Decizii

| Zonă | Decizie |
|---|---|
| Aspect | Păstrăm tokenii, bonul, markerul, temele și machetele aprobate; capturi reale după implementare. |
| Black Friday | Listă, ținte și buget + bilanț pentru intervalul ales. Clarificare aprobată: 6 noiembrie 2026, 07:15 → 7 noiembrie, 00:00, Europe/Bucharest; sfârșit exclusiv, date și ore editabile în configurație/UI. Comenzile fără oră precisă se numără separat și nu sunt incluse. |
| Bugete | Utilizatorul stabilește sumele; fără buget financiar implicit inventat. Lunar și anual; comenzile în curs separat. |
| Calcule | Reutilizăm `loadAnalysis` și motorul existent; nu modificăm rezultatele raportului de referință. Sume întregi în bani. |
| Prețuri | Numai pagina eMAG deschisă de utilizator. Comparație strictă cu denumirea completă; fără subșir/fuzzy sau pretins minim de piață. Lipsa ori ambiguitatea se afișează. |
| Stocare | Preferințe, listă și etichete criptate local; actualizări atomice între tab și panou; ștergerea elimină tot și invalidează consumatorii vechi. |
| Demo | Același generator de date ca raportul existent, fără cont; modificările demo numai în memorie. |
| Distribuire | PNG local al cardului previzualizat, fără identificatori sau nume de produse; suma poate fi ascunsă. |
| Publicare | Actualizare aprobată de Robert la 08.11.2026: după verificări, un singur commit și push de pe PC-ul curent; fără tag, lansare sau publicare în magazin. |
| Versiune | Cerută ulterior de Robert, după confirmarea celor șase file în Chrome: extensia 1.1.0. Lansarea oficială are predare separată în `docs/handoff/2026-11-08-lansare-extensie.md`. |

Sursă calendar: https://about.emag.ro/2026/11/05/black-friday-2026-emag-a-pregatit-peste-18-milioane-de-produse-la-cel-mai-mic-pret-din-an/

## Contracte între bucăți

1. Date/calcul: `extensie/src/cumparaturi/shopping_store.js` exportă `createShoppingStore({demo, defaults})` -> `{read(), update(mutator), subscribe(listener), dispose()}`; `update` citește ultima stare și mută/salvează atomic; întoarce noua stare. `defaults` vine din config. Schema: `{schema:2, campaign:{from,to,start_time,end_time,time_zone,budget_bani:null}, wishlist:[], budgets:{}, tags:{}}`. Migrarea schemei 1 păstrează preferințele, iar orele neconfigurate nu inventează un bilanț. Wishlist: `{id,name,url,price_bani:null,target_bani:null,observed_at:null,selected:true}`; cheia de buget este `YYYY` sau `YYYY-MM`, valoare în bani; tags mapează cheia stabilă a unei achiziții la un text liber validat.
2. Date/calcul: `extensie/src/cumparaturi/shopping_insights.js` exportă `createShoppingInsights(entry)` async -> `{summary,purchases,years,period(from,to)}`. `period` întoarce un rezumat compact prin însumarea atribuirilor `paid_by_order`, calculate de motor o singură dată pe toate comenzile și retururile, înainte de filtrare. Ajustare de implementare: un retur comun nu se redistribuie după filtrarea unei luni. Rezumatul de referință al motorului rămâne identic. `purchases` are `{id,order_id,date,name,seller,category,qty,paid_bani,unit_bani}` pentru achizițiile păstrate; chei structurale stabile și sume din registru. Fără comenzi brute: fallback anual din rezumat, lunar indisponibil explicit.
3. Interfață: `extensie/src/cumparaturi/shopping_app.js` exportă `mountShoppingApp(root,{entry,demo,defaults})` -> Promise<{dispose()}>. Include navigația Raport/Black Friday/Buget/Retururi/Etichete/Bilanț și reutilizează raportul existent. Agentul UI poate integra în `ecrane/report_screen.js`; coordonatorul îi pasează `entry` și `defaults` din main. Containerul `shopping-root` este lângă `report-root`; CSS separat `cumparaturi/shopping.css`.
4. Chrome: `extensie/src/panou/` plus `sidepanel.html` și stiluri proprii. Importă store/insights de mai sus; utilizează ultima analiză reală, niciodată date demo în comparațiile reale. Intrarea curentă de produs se citește prin `chrome.scripting` pe tab eMAG, fără cereri externe suplimentare. Clicul iconiței pe produs deschide panoul; altfel păstrează fila aplicației. Agentul Chrome deține `background.js`; coordonatorul deține manifestul.
5. Coordonator: `main.js`, `aplicatie.html`, manifest, build, config, generator demo, documentație și verificarea finală. Creează `generat/shopping_config.js` și `generat/shopping_demo.js` la build. Ultimul exportă `{orders,returns}` din generatorul existent; summary se primește separat din `window.EMAG_DEMO_DATA`.

Agentul anunță orice ajustare de contract înainte să o implementeze; fișierele sunt disjuncte. Niciun agent nu pornește alți agenți și nu modifică fișierele altuia.

## Ordine și verificări

- Baseline: build strict, unitare, demo e2e; snapshot al build-ului original pentru comparații.
- Implementare în paralel: date, Chrome, UI; fiecare cu teste proprii și build într-un folder propriu din logs/.
- Integrare: module reale, reload/persistență, date șterse, demo fără rețea, interval BF trecut și bugete lunare.
- Verificare: parser, unitare și paritate, e2e extensie pe browser instalat, layout îngust și ambele teme, exportul real PNG, verificare defensivă și review al codului.
- Capturi înainte/după cu date inventate și toate textele noi de legătură vizibile. Nicio captură din cont real.

## Riscuri și limite

- Numele din comenzi nu includ identificatori de produs: compararea refuză denumirile diferite sau trunchiate; nu prezintă potriviri aproximative drept certe.
- Retururile pot veni după intervalul de cumpărare; se atribuie comenzii, ca raportul existent. Filtrarea păstrează legăturile relevante fără a dubla restituiri comune.
- Totalurile unei analize vechi nu sunt live; data analizei rămâne vizibilă.
- API-urile native ale extensiei se verifică în Chromium; o redare în alte motoare nu echivalează cu extensia Chrome instalată.

## Nu intră

Monitorizare automată a prețurilor în fundal, notificări, server/cloud, prețuri din alte magazine, conturi noi, abonamente sau integrare bancară.

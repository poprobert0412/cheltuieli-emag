# Date și calcule — progres

1. Citit contractul și modulele existente: persistență AES-GCM/Web Locks/generații, registru, retururi și totaluri plătite.
2. Stocare: implementat read/modify/write sub același Web Lock, fără lock imbricat; generație capturată per store, notificări între contexte, dispoziție și demo exclusiv în memorie.
3. Calcul: implementat loadAnalysis, id structural pe order/seller/name/occurrence, preț unitar plătit după reduceri și perioade inclusive.
4. Ajustare aprobată de coordonator: paid_totals acumulează aceleași atribuiri și pe comandă în aceeași trecere; spend_analysis expune paid_by_order separat. Nu se modifică summary sau schema exportată și nu se sintetizează retururi.
5. Validare: bani safe-integer nenegativi/null, calendar, texte fără control/bidi, URL produs eMAG HTTPS canonic comun cu panoul. URL gol este permis pentru produs adăugat manual, fără observație de preț.
6. Parser: toate cele 7 module de producție și cele 3 fișiere de teste parsate cu node --check.
7. Teste finale: 332/332 teste relevante trecute (shopping_store, shopping_insights, criptare, paritatea analizei); log logs/functii-2026-11-08/date/_meta/regresii-final.log.
8. Build strict: trecut, 105 fișiere, build separat logs/functii-2026-11-08/date-dist; log _meta/build-final.log.
9. E2E Edge: 4/4 trecute pe două pagini reale de extensie, concurență, criptare, reload, analiză nouă și ștergere; zero erori/CSP/rețea externă; log _meta/e2e-final.log. Browser închis de harness, fără server.
10. Mutații: pe copii în logs/functii-2026-11-08/date/mutatii au fost detectate prețul de listă în locul celui plătit, omiterea atribuirilor per comandă și ignorarea generației de ștergere; loguri _meta/mutatie-*.log. Copia de mutație folosește junction spre extensie/node_modules; sursele au rămas intacte.
11. Review verifica-cod (ponytail-review, thermo-nuclear, ponytail-debt) pe fișierele proprii și apelanți: fără constatări deschise; zero shortcut-uri noi. Încărcare considerată: un utilizator, două contexte Chrome, mii de linii. Alocarea rămâne liniară; sortarea achizițiilor/categoriilor este cea necesară afișării.

## Contract final

- createShoppingStore({demo,defaults}) -> read/update/subscribe/dispose; subscribe primește (state,error), ștergerea trimite null și invalidează scriitorul. Dependențele storage/persistence/changes sunt injectabile în teste.
- createShoppingInsights(entry) -> summary identic motorului, purchases păstrate, years string[], period(from,to) async.
- period oferă available, detail_available, meta.{from,to,orders,missing_dates}, paid.{spent_bani,spent_units,products_kept_bani,fees_bani,credit_returns_bani,refund_differences_bani,funnel,reconciliation.in_progress_bani}, funnel cu unități, by_category păstrat și by_year compact.
- Fără raw: numai intervalele de ani întregi pot folosi totalurile by_year; lunile întorc available:false și paid:null. Nu se inventează produse sau zerouri lunare.
- Unit_bani este media pe unitate rotunjită la ban când linia are rest; paid_bani păstrează totalul exact.

## Limite și predare

Nu s-au modificat UI/config/manifest/build sau conturi reale; fără commit/push. Coordonatorul integrează și rulează auditorul și verificarea vizuală finală. Nu există proces/server rămas. Nu s-au făcut capturi deoarece bucata nu schimbă interfața. Perioadele exclud comenzile fără dată și expun numărul lor; rezumatul complet le păstrează.

Ownership: shopping_store.js, shopping_schema.js, shopping_insights.js, shopping_period.js, private_storage.js, paid_totals.js, spend_analysis.js, testele shopping_store/shopping_insights/shopping_data.

## Reluare: campanie cu ore — contract aprobat și implementat

12. Schema2: campaign păstrează from/to (YYYY-MM-DD) și adaugă start_time/end_time (HH:MM), time_zone Europe/Bucharest; orele vin exclusiv din config/formular, fără valori de eveniment în algoritm.
13. campaign_time.js validează calendarul și orele și convertește prin Intl în instanțe precise. Orele locale inexistente sau ambigue la DST sunt refuzate; offseturile explicite invalide sunt refuzate. O comandă cu offset valid este tratată ca instanță explicită, independent de fusul calculatorului.
14. insights.campaign(campaign) folosește [start,end), inclusiv la miezul nopții; insights.period(date,date) rămâne inclusiv pe zile întregi. Ambele însumează aceeași atribuire financiară, fără recalcularea retururilor.
15. Comenzile fără oră precisă care ar putea aparține zilelor intervalului sunt excluse și numărate în meta.missing_times; lipsa datei este separată în meta.missing_dates. Sfârșitul și începutul exacte sunt disponibile în meta.end_ms/start_ms pentru UI.
16. Migrarea schema1→2 recitește ultima stare sub lacăt și păstrează lista/etichetele/bugetele/datele campaniei. Folosește orele config; dacă intervalul vechi devine invalid, păstrează start_time/end_time null și cere alegere explicită prin available:false,time_required:true,paid:null.
17. Test roșu înainte de implementare: noul campaign_time.test.js a picat deoarece API-ul lipsea; log _meta/ore-red.log.
18. Verificări finale ore: parser pe cele 5 module și 3 teste; 341/341 teste relevante + criptare + paritate trecute (_meta/ore-regresii.log), 15/15 și în proces TZ=Pacific/Honolulu (_meta/ore-fus-honolulu.log).
19. Mutații actualizate: 5/5 detectate; suplimentar includerea capătului final și pierderea wishlist la migrare (_meta/ore-mutatii.log). Testele folosesc date și ore inventate din 2031, fără date din contul real.
20. Build strict cu ore: 106 fișiere (_meta/ore-build.log); e2e date 4/4 în Edge real, zero consolă/CSP/rețea externă (_meta/ore-e2e.log). Browser închis de harness; fără server, commit sau push.

Exporturi comune: shopping_schema.js reexportă isShoppingDate/isShoppingTime/validateCampaign; validateCampaign(campaign) întoarce {start_ms,end_ms,time_required}. Dacă start/end sunt null, UI afișează lipsa orelor; sfârșitul trecut se stabilește prin Date.now() >= end_ms, numai când end_ms nu este null.

Review verifica-cod al reluării: modulele de calendar, stocare și proiecție rămân separate; filtrarea financiară este comună, fără formulă duplicată. Fără constatări deschise sau shortcut-uri noi. Root verifică UI și contul real; acest agent nu a accesat/înregistrat date reale și nu a atins config/UI/motorul financiar în reluare.

# Black Friday cu ore exacte — interfață

1. `campaign_view.js` folosește contractul comun schema 2: datele plus `start_time`, `end_time` și `time_zone`. Afișează două grupuri compacte Din/Până, fiecare cu dată și oră HH:mm în format 24 h independent de browser; tastatura text permite introducerea caracterului `:` și pe telefon.
2. Fusul este explicat vizibil prin „Ora României. Sfârșitul ales nu intră în perioadă.” Calculele și conversiile rămân exclusiv în `insights.campaign`/`validateCampaign`, nu în renderer.
3. Intervalul este validat la blur și submit, cu focus pe primul câmp greșit; sfârșitul egal cu începutul și 24:00 sunt refuzate. Focusul după Enter și la 320 px este păstrat.
4. Orele null cer alegerea ambelor capete și nu produc totaluri zero. Comenzile fără oră sigură și cele fără dată sunt avertizate separat de totaluri.
5. CSS-ul păstrează tokenii și stilul existent; la 320 px grupurile sunt unul sub altul, iar data și ora fiecărui capăt rămân alăturate.

## Verificări

- Parser JS și build strict propriu: trecute, `logs/functii-2026-11-08/ui-dist`.
- Test nou văzut roșu pe copia build-ului anterior `ui-clock-before`, la câmpul de oră lipsă: `_meta/ui-clock-rosu.log`.
- Grupul nou Edge: 5/5; suita UI completă după integrare: 22/22, 37,3 s, zero erori consolă/CSP/rețea externă (`_meta/ui-clock-e2e-complet.log`).
- Fixtură integral inventată, 14–15 februarie 2031: 01:00 și 07:59:59 excluse, 08:00 inclus, 09:59:59 din ultima zi inclus, 10:00 exclus; mutarea sfârșitului la 10:01 include comanda de la 10:00. Valori financiare numai din fixtură, fără identificatori sau produse reale.
- Capturi înainte/după pe aceeași fixtură, aceleași date/lățimi/teme: `docs/extensie/capturi/2026-11-08-implementare/plansa-bf-ore-desktop-inainte-dupa.png` și `plansa-bf-ore-mobil-inainte-dupa.png`; trimise imediat coordonatorului.
- Niciun server pornit, browserele de test sunt închise. Contul real este testat exclusiv de coordonator. Fără commit/push în subtask.

GATA. Fișierele UI sunt înghețate pentru integrare.

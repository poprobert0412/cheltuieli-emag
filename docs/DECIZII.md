# Decizii deja luate

Lista deciziilor autorului, cu data. Auditurile și propunerile noi nu le redeschid fără un motiv nou (de exemplu, eMAG își schimbă paginile). Coloana „Unde” arată fișierele afectate; la o parte din ele, un comentariu din cod trimite la decizie cu aceeași dată.

| Data | Decizia | Unde |
|---|---|---|
| 4 oct. 2026 | Sesiunea eMAG rămâne salvată local, în `.profil_browser/`, ca să nu te loghezi la fiecare rulare; se șterge cu `sterge_sesiunea.bat` / `--sterge-sesiunea`. | `emag_spend/browser_session.py`, `session_cleaner.py` |
| 4 oct. 2026 | „Același produs” la istoricul prețurilor = același model; culoarea nu contează, capacitatea și dimensiunea da. | `emag_spend/product_key.py` |
| 5 oct. 2026 | În raportul demonstrativ, numerele de comandă sunt text simplu, nu linkuri: eMAG redirecționează numerele inventate spre lista de comenzi. | `emag_spend/site_demo_writer.py`, `interfata/assets/dashboard.js` |
| 5 oct. 2026 | „Produse ajunse în showroom” / „ajunse la …” = comandă în curs, nu status necunoscut. | `emag_spend/block_status.py` |
| 5 oct. 2026 | Distribuția: o singură arhivă pentru Windows, macOS și Linux; la prima pornire lansatorul aduce uv (verificat cu SHA-256), Python și pachetele, în folderul programului. Fără ZIP cu Python inclus (ar fi trebuit câte unul pentru fiecare sistem și procesor) și fără `.exe` nesemnat. | `porneste.*`, `instaleaza.bat`, `instalare/` |
| 5 oct. 2026 | Cifra principală e „plătit efectiv”, din „Total plătit” al fiecărui bloc eMAG (după vouchere și reduceri, cu transportul), nu prețul de listă. | `emag_spend/paid_totals.py` |
| 5 oct. 2026 | Restituirea „Generare sold” (sold eMAG) e credit, ca voucherul: nu se scade la retur, fiindcă soldul scade „Total plătit” al comenzii în care e folosit. | `config/restituiri.json`, `emag_spend/refund_modes.py` |
| 5 oct. 2026 | Pe bonul din pagina de prezentare, rândul totalului scrie „= Plătit” (varianta lungă rupea rândul și făcea bonul să sară la animație). | `interfata/index.html`, `interfata/assets/site-simulator.js` |
| 6 oct. 2026 | O actualizare întreruptă se desface la pornirea următoare, înaintea pregătirii lansatorului și a restului programului (`python -m emag_spend.update_recovery`). Ordinea recuperare → pregătire → program e contract cu versiunile deja instalate. | `porneste.*`, `emag_spend/update_recovery.py` |
| 6 oct. 2026 | README scurt (ce face, de ce, pornire, capturi reale din aplicație pe datele demonstrative); detaliile stau în `docs/CALCUL.md`, `docs/INTREBARI.md`, `docs/INSTALARE.md` și `SECURITY.md`. | `README.md`, `docs/` |
| 5 oct. 2026 | Actualizări ca la o aplicație: aplicația locală verifică singură, la pornire, dacă există o versiune nouă pe GitHub (o cerere fără date personale, dezactivabilă cu `EMAG_UPDATE_CHECK=0`); instalarea pornește doar când apeși „Actualizează acum” (sau `--actualizeaza`), cu arhiva verificată prin SHA-256, datele tale păstrate, revenire automată la eroare și repornire pe versiunea nouă. | `emag_spend/update_*.py`, `app_update_job.py`, lansatoarele |

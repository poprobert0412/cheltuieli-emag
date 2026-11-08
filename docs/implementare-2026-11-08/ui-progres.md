# Interfață cumpărături — progres

1. Citit contractul și capturile aprobate 1, 3, 4, 5, 6; tokenii vin din app.css.
2. Implementat module separate: navigație și lifecycle, Black Friday, buget, retururi, etichete, bilanț și export canvas comun previzualizării/PNG.
3. Integrare report_screen: entry/defaults, anulare la hideReport, erori capturate, ștergere accesibilă pe start.
4. Parser JS și build strict propriu: trecut (`logs/functii-2026-11-08/ui-dist`).
5. Unitare: 3/3; e2e Edge final: 17/17, 27,3s după corecturile finale, zero consolă/CSP/rețea externă (`_meta/ui-unit.log`, `_meta/ui-e2e.log`).
6. Verificat: buget anual/lunar, CRUD listă și validare la blur, etichete/filtru, PNG cu pixeli identici, demo exclusiv în memorie, persistență criptată/reload/sincronizare două pagini, ștergere globală, consumator vechi refuzat și montare anulată.
7. Capturi: `docs/extensie/capturi/2026-11-08-implementare/plansa-ecrane-noi.png` (5×3) și `plansa-raport-inainte-dupa.png` (baseline real vs UI, desktop/mobil, ambele teme); transmise coordonatorului imediat.
8. Corectat focusul după click/Enter pe Salvează: cheie stabilă, restaurare numai dacă focusul aparținea vederii înlocuite, fallback fila activă dacă formularul se închide. Testul a prins și copiii unui details închis care au recturi, dar refuză focusul; remedierea verifică activeElement.
9. Filtrul de etichete separă `tag:<text>` de opțiunile interne; regresie explicită pentru eticheta liberă `__untagged`.
10. Motoare web: Firefox 8/8 combinații curate; WebKit controale/layout/focus/lună/PNG 8/8 funcționale, cu poarta CSP rămasă explicit roșie din cauza selectului nativ demonstrat separat. Axe: 80 scanări, 0 violations și 0 incomplete; diagnosticele native și ale capturilor sunt raportate separat în `ui-motoare.md`, fără allowlist.
11. Buget fără comenzi: lista anilor include anul calendaristic RO și anii bugetelor salvate, fără sume implicite; test văzut roșu pe build-ul vechi, verde după fix, inclusiv salvare/reload și bugete vechi lunare/anuale.
12. GATA; freeze final confirmat. Toate serverele de test și browserele proprii închise, niciun commit/push.
13. Continuare ore BF: date+HH:mm24h, ora României și capăt exclusiv, avertizări separate, ore null fără totaluri inventate; raport `ui-ore-bf.md`. Build strict și UI complet22/22 (37,3s), cu regresie roșu→verde și capturi înainte/după inventate. GATA, freeze UI reconfirmat.

## Decizii de implementare

- Retururile afișează pașii reali din date când există; fără pași inventați din statusul final.
- Formularele sunt validate la blur și submit; bani null rămân absenți, fără buget implicit.
- PNG-ul descarcă exact canvasul vizibil, folosind aceiași pixeli și tokeni ai temei.
- Testul PNG a picat pe diferența de rotunjire RGBA între toBlob/toDataURL; exportul folosește acum aceeași serializare toDataURL, iar comparația pe fiecare pixel trece fără toleranță.
- Capturile au context `locale: ro-RO`; Edge continuă să afișeze data nativă în formatul propriei interfețe US, fără format impus în cod.
- Ownership disjunct: nu schimb store/insights, main, manifest, build sau panoul Chrome.

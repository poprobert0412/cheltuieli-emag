# Lansarea extensiei 1.1.0 — predare din 8 noiembrie 2026

Scop: publicarea extensiei Chrome „Cât am cheltuit pe eMAG”, versiunea 1.1.0, după implementarea celor șase funcții și acceptanța pe cont real. Acest document pregătește lansarea; nu consemnează o trimitere în magazin.

## Ce există și ce este decis

- Manifestul este sursa versiunii extensiei, separat de `emag_spend/version.py`.
- Acceptanța completă pe cont real a trecut toate cele șase funcții; colectarea și calculele sunt identice JS/Python. Datele și exporturile reale sunt numai în `iesiri/`, ignorat de Git.
- Robert a confirmat cele șase file în Chrome după reîncărcare; versiunea nouă a fost cerută ulterior.
- E25 autorizează un singur commit și push de pe PC după teste. E21/E22 păstrează lansarea publică și operarea de către asistent; login/2FA/plățile sunt ale titularului.
- Nu se schimbă designul, bugetele personale, numele, GPL-3.0 sau permisiunile ca pretext de lansare. Fără date reale în capturile magazinului.

## Reguli de citit înainte de operare

Regulile permanente și locale; `orchestrare.md`, `capturi-interfata.md`, `sincronizare-github.md`, `ci-cd.md`, `site-testare.md`, `site-legal.md`, `securitate-web.md`. Citește `docs/DECIZII.md`, `docs/MAGAZIN-EXTENSIE.md`, `docs/aprobare-confidentialitate-2026-11-08.md` și raportul verificării finale. Nu porni agenți suplimentari sau servicii cu plată din proprie inițiativă.

## Pașii rămași

1. **[C] Verificări și Git:** pachetul final 1.1.0, manifest/changelog coerente, scanarea indexului, un singur commit/push autorizat de pe PC, apoi verificarea tuturor workflow-urilor pornite de push. Nu crea etichetă `v1.1.0` automat: workflow-ul `lansare.yml` publică și aplicația desktop, nu doar extensia.
2. **APROBARE [R] — textele noi:** aprobarea concretă a completărilor din `docs/aprobare-confidentialitate-2026-11-08.md`. **[C]** după aprobare, integrează textele în politica publică și în formularul magazinului; verifică URL-ul public. Aprobările vechi nu acoperă automat noile declarații.
3. **[C]/[R] Contul Chrome Web Store:** inspectează starea reală din dashboard, fără a presupune că există deja un element public. [R] face login/2FA și orice plată necesară, după prezentarea costului afișat. Nu introduce credențiale în fișiere sau în chat.
4. **[C] Ciorna:** dacă elementul există, încarcă pachetul nou pe același element; altfel pregătește un element nou. Completează descrierea, `sidePanel`, practicile de confidențialitate și instrucțiunile recenzentului. Verifică materialele la dimensiunile cerute de dashboard; numai capturi cu date inventate.
5. **[C] Recenzie și verificare:** trimite pachetul numai după completarea punctelor anterioare; consemnează starea reală a recenziei. După aprobare, verifică pagina publică și instalarea oficială într-un profil separat, inclusiv analiza, panoul, persistența și ștergerea. Nu declara lansarea terminată doar pentru că ZIP-ul a fost încărcat.

## Calendar și surse

Google cere o versiune mai mare pentru un pachet actualizat și recenzează și actualizările. Recenzia durează de regulă câteva zile, dar poate dura săptămâni; ținta lui Robert de o săptămână nu poate fi garantată înaintea aprobării Google. Surse oficiale verificate pe 8 noiembrie 2026: [actualizare](https://developer.chrome.com/docs/webstore/update), [publicare](https://developer.chrome.com/docs/webstore/publish), [recenzie](https://developer.chrome.com/docs/webstore/review-process).

Pricy și o reorganizare vizuală a planificatorului Black Friday sunt subiecte de produs, separate de încărcarea în magazin. Nu adăuga alerte, crawling de prețuri sau servicii externe ca parte implicită a lansării.

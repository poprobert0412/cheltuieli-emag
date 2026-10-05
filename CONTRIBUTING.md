# Cum contribui

Mulțumim că vrei să ajuți. Proiectul e mic și lucrează cu date personale (istoricul de cumpărături al cuiva), deci regulile de mai jos sunt mai stricte decât la un proiect obișnuit.

## Înainte de orice

- **Probleme și idei:** deschide un [Issue](../../issues/new/choose) și completează formularul. **Nu atașa și nu lipi date personale**: `comenzi.json`, `retururi.json`, `analiza.json`, conținutul `iesiri/`, `logs/`, `.profil_browser/`, capturi cu comenzi reale. Folosește exemple inventate.
- **Vulnerabilități:** nu le descrie într-un Issue public; vezi [SECURITY.md](SECURITY.md).
- Pentru o schimbare mare, deschide întâi un Issue, ca să nu muncești degeaba.

## Mediu de lucru

```
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

Testele folosesc pagini și comenzi inventate și nu intră în niciun cont. Cele care verifică raportul și interfața pornesc Edge sau Chrome fără fereastră și se sar dacă nu e instalat niciunul. Mai multe detalii: [docs/INSTALARE.md](docs/INSTALARE.md#pentru-programatori).

## Regulile codului

- **Un fișier = o singură treabă, numit după ce face** (`order_parser.py`, `session_cleaner.py`). Fără `utils.py`, `helpers.py`, `common.py`.
- **Antet de 3–8 rânduri la fiecare `.py`** (ce face, ce primește, ce dă înapoi, ce nu e treaba lui) și **docstring la fiecare funcție**. Comentariul spune *de ce*, codul arată *cum*. Când schimbi codul, schimbi și comentariul.
- **Fără valori hardcodate din date reale.** Praguri și limite: constante cu nume, cu un comentariu care spune de ce are acea valoare. Valori care depind de mediu: variabile `EMAG_*`, documentate în `emag_spend/settings.py`. Reguli care depind de produse: date în `config/*.json`, nu în cod.
- **Exemplele și testele folosesc doar date inventate**: niciun nume, adresă, telefon, e-mail, număr de comandă sau produs real din contul cuiva.
- **Testele-gardă nu se ocolesc.** `tests/test_garda_parole.py`, `test_garda_retea.py` și `test_garda_scriere.py` opresc tastarea în pagini, citirea cookie-urilor, modulele de rețea neașteptate și scrierile în afara `iesiri/`, `logs/` și `.profil_browser/`. Dacă ai nevoie de o excepție, explic-o în pull request: fiecare excepție existentă are un motiv scris în fișierul gărzii.
- **Calculele nu se schimbă fără teste** care arată ce se schimbă și de ce.
- Textele pentru utilizator sunt **în română, cu diacritice**. Fișierele `.bat` au sfârșituri de rând CRLF, restul LF (vezi `.gitattributes`).
- Dependențele rămân fixate la versiuni exacte; adăugarea uneia noi se justifică în pull request.

## Pull request

Completează lista din șablon. Pe scurt: testele trec, nu ai date personale, nu ai secrete, documentația e la zi.

Prin trimiterea unui pull request accepți ca modificările tale să fie distribuite sub aceeași licență ca proiectul, **GPL-3.0** (vezi [LICENSE](LICENSE)).

# Prompt de QA independent — extensia de cumpărături

Verifică numai în citire implementarea din 8 noiembrie 2026 din acest proiect. Citește regulile permanente și locale, planul `docs/planuri/2026-11-08-functii-extensie.md`, deciziile E23–E24 și `docs/implementare-2026-11-08/verificare-finala.md`. Nu schimba designul, datele sau pragurile; nu face commit/push și nu folosi profilul personal. Nu porni agenți suplimentari fără scara aprobată.

1. Construiește într-un folder nou, numai pentru QA, și compară calculele cu Python; raportul de referință trebuie să rămână identic la ban.
2. În Edge cu extensia reală și pagini eMAG inventate: listă/ținte/buget, schimbarea intervalului BF trecut/viitor, buget lunar/anual/nul/zero, retururi, etichete libere, PNG cu și fără sumă.
3. Probează două pagini și panoul simultan: actualizări concurente, reload, analiză înlocuită, ștergere, scriere întârziată, ciphertext corupt și cotă plină; datele vechi nu se recreează după ștergere.
4. Panoul: clic real, alt tab/navigare în timpul citirii, produs fără preț, oferte ambigue, denumiri apropiate cu alte dimensiuni/culori și două cumpărări în aceeași zi. Nicio potrivire prin subșir și nicio cerere în fundal.
5. Suprafețe web: Edge/Firefox/WebKit, 320/390/1024/1440 px, ambele teme, tastatură/focus, formulare, scroll orizontal, axe și console/CSP. Separă modulele web de API-urile native Chrome.
6. Confirmă că demo nu scrie date reale și că imaginea PNG nu conține produse ori identificatori. Compară pixelii exportului cu previzualizarea.
7. APROBARE înainte de profilul personal, cont real sau publicare. Pentru verificarea publică eMAG fără cont raportează blocajul HTTP ca atare; nu inventa selectori după pagini indisponibile. Texte legale propuse în addendum, nu aprobate automat.

Raport final: test → rezultat real, matrice fișier × motor, constatări cu fișier:linie și caz reproductibil, capturi înainte/după pe aceleași date. Menționează testele sărite și oprește numai serverele/profilurile pornite de QA. Deciziile noi de produs/design se propun, nu se implementează în audit.

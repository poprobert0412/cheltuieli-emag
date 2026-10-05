"""Teste pentru fișierele statice ale aplicației locale (emag_spend/app_static.py și ruta lor din app_server.py).

Verifică lista albă (pagina aplicatie.html + doar ce cere ea; fără demo-data.js și fără site-ul explicativ dacă nu e cerut), apoi
că NIMIC din afara ei nu se servește: traversare cu `..`, `%2e%2e`, `%5c`, `\\`, `//`, nume 8.3, `::$DATA`, majuscule, foldere, și
că /.git/, /config/, /emag_spend/, /iesiri/ dau 404. Joncțiuni spre exterior nu intră în listă. Valorile sunt inventate;
fiecare test spune în mesaj ce s-a încălcat și de ce contează.
"""

import pytest

from emag_spend import app_static
from emag_spend.app_server import INTERFACE_DIR
from tests.app_support import running_app, write_interface
from tests.test_app_runs import make_directory_link

MARKER = "MARKER-INVENTAT-NEPUBLIC"


@pytest.fixture
def interface(tmp_path):
    """Un folder interfata/ inventat și un fișier secret lângă el (în afara lui)."""
    (tmp_path / "secret.txt").write_text(MARKER, encoding="utf-8")
    folder = write_interface(tmp_path / "interfata")
    (folder / "assets" / "notite.txt").write_text(MARKER, encoding="utf-8")
    (folder / "assets" / "date.json").write_text('{"secret": "' + MARKER + '"}', encoding="utf-8")
    return folder


@pytest.fixture
def app(tmp_path, interface):
    """Server real care servește folderul interfata/ inventat."""
    with running_app(tmp_path, interface_dir=interface) as running:
        yield running


# ---------- lista albă ----------

def test_the_page_and_the_files_it_references_are_served_without_a_token(app, interface):
    """aplicatie.html, scriptul și stilul ei se servesc cu tipul potrivit și FĂRĂ token (pagina trebuie să se încarce înainte să citească tokenul)."""
    page = app.call("GET", "/aplicatie.html", token=False)
    assert page.status == 200 and page.headers["content-type"] == "text/html; charset=utf-8"
    assert page.body == (interface / "aplicatie.html").read_bytes()
    script = app.call("GET", "/assets/app.js", token=False)
    assert script.status == 200 and script.headers["content-type"] == "text/javascript; charset=utf-8" and b"aplicatia" in script.body
    style = app.call("GET", "/assets/app.css", token=False)
    assert style.status == 200 and style.headers["content-type"] == "text/css; charset=utf-8"


@pytest.mark.parametrize("path", ["/assets/demo-data.js", "/assets/site.js", "/index.html", "/assets/notite.txt", "/assets/date.json"])
def test_files_the_page_does_not_ask_for_are_not_served(app, path):
    """demo-data.js, site-ul explicativ (index.html, site*.js) și orice fișier necerut de pagină -> 404: nu servim mai mult decât are nevoie aplicația."""
    reply = app.call("GET", path, token=False)
    assert reply.status == 404 and MARKER.encode() not in reply.body, f"{path} a fost servit deși pagina aplicației nu îl cere"


def test_demo_data_is_served_only_when_the_page_asks_for_it(tmp_path):
    """demo-data.js intră în lista albă doar dacă aplicatie.html îl cere cu <script src>."""
    folder = write_interface(tmp_path / "interfata", '<script src="assets/app.js"></script><script src="assets/demo-data.js"></script>')
    assert "/assets/demo-data.js" in app_static.StaticFiles(folder).urls
    folder = write_interface(tmp_path / "alta", '<script src="assets/app.js"></script>')
    assert "/assets/demo-data.js" not in app_static.StaticFiles(folder).urls


def test_only_the_expected_urls_are_whitelisted_for_a_typical_page(interface):
    """Lista albă a paginii-model conține exact pagina, scriptul și stilul."""
    assert app_static.StaticFiles(interface).urls == {"/aplicatie.html", "/assets/app.js", "/assets/app.css"}


def test_external_absolute_and_odd_references_do_not_create_routes(tmp_path):
    """Referințe externe (https, //), data:, cu `..`, cu % sau \\, cu extensii nepermise (.json, .txt) sau către fișiere inexistente nu intră în lista albă."""
    folder = write_interface(tmp_path / "interfata", "".join([
        '<script src="https://evil.example/x.js"></script>', '<script src="//evil.example/y.js"></script>', '<script src="data:text/javascript,alert(1)"></script>',
        '<script src="../secret.txt"></script>', '<script src="assets/../../secret.txt"></script>', '<script src="assets%2fapp.js"></script>',
        '<script src="assets\\app.js"></script>', '<script src="assets/date.json"></script>', '<script src="assets/notite.txt"></script>',
        '<script src="assets/nu-exista.js"></script>', '<script src="assets/app.js?v=3#x"></script>', '<img src="/assets/app.css">', '<link href="">',
    ]))
    (folder / "assets" / "date.json").write_text("{}", encoding="utf-8")
    (folder / "assets" / "notite.txt").write_text("x", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    urls = app_static.StaticFiles(folder).urls
    assert urls == {"/aplicatie.html", "/assets/app.js", "/assets/app.css"}, f"lista albă conține în plus: {sorted(urls - {'/aplicatie.html', '/assets/app.js', '/assets/app.css'})}"


def test_images_and_icons_the_page_asks_for_get_the_right_content_type(tmp_path):
    """Pictograma și imaginile cerute de pagină (svg, png, ico) se servesc cu tipul lor; executabilele nu se servesc nici dacă pagina le cere."""
    folder = write_interface(tmp_path / "interfata", '<link rel="icon" href="assets/i.svg"><img src="assets/p.png"><link rel="icon" href="favicon.ico"><script src="assets/rau.exe"></script>')
    (folder / "assets" / "i.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (folder / "assets" / "p.png").write_bytes(b"\x89PNG inventat")
    (folder / "favicon.ico").write_bytes(b"ico inventat")
    (folder / "assets" / "rau.exe").write_bytes(b"MZ inventat")
    files = app_static.StaticFiles(folder)
    assert files.urls == {"/aplicatie.html", "/assets/i.svg", "/assets/p.png", "/favicon.ico"}
    assert files.read("/assets/i.svg")[1] == "image/svg+xml" and files.read("/assets/p.png")[1] == "image/png" and files.read("/favicon.ico")[1] == "image/x-icon"


def test_fallback_patterns_apply_while_the_page_does_not_exist_yet(tmp_path):
    """Cât timp aplicatie.html lipsește: doar assets/app*.js|css, dashboard.* și site.css; nimic din site-ul explicativ."""
    folder = tmp_path / "interfata"
    (folder / "assets").mkdir(parents=True)
    for name in ("app.js", "app-boot.js", "app.css", "dashboard.js", "dashboard.css", "site.css", "site.js", "site-viewer.js", "demo-data.js", "apple.js", "notite.txt"):
        (folder / "assets" / name).write_text("x", encoding="utf-8")
    (folder / "index.html").write_text("<html></html>", encoding="utf-8")
    urls = app_static.StaticFiles(folder).urls
    assert urls == {"/assets/app.js", "/assets/app-boot.js", "/assets/app.css", "/assets/dashboard.js", "/assets/dashboard.css", "/assets/site.css", "/assets/apple.js"}, sorted(urls)
    # „apple.js” se potrivește cu tiparul assets/app*.js (și e doar un fișier de aceeași familie de nume); site.js și demo-data.js rămân în afară


def test_a_missing_interface_folder_gives_an_empty_whitelist(tmp_path):
    """Fără folderul interfata/ lista albă e goală și serverul tot pornește (răspunde 404 la fișiere)."""
    assert app_static.StaticFiles(tmp_path / "nu_exista").urls == frozenset()


# ---------- nimic din afara listei ----------

TRAVERSAL_TARGETS = [
    "/../secret.txt", "/assets/../../secret.txt", "/assets/../aplicatie.html", "/assets//app.js", "///etc/passwd",
    "/%2e%2e/secret.txt", "/%2E%2E/secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/%2e%2e%2fsecret.txt", "/..%2fsecret.txt", "/assets/..%5csecret.txt",
    "/assets%5capp.js", "/assets\\app.js", "/..\\secret.txt", "/assets/app.js%00.png", "/assets/app.js\x00", "/aplicatie.html%20",
    "/aplicatie.html.", "/aplicatie.html::$DATA", "/aplicatie.html:Zone.Identifier", "/assets/app.js::$DATA", "/APLICATIE.HTML", "/Aplicatie.html",
    "/ASSETS/APP.JS", "/Assets/app.js", "/APLICA~1.HTM", "/ASSETS~1/APP~1.JS", "/assets/app*.js", "/assets/app?.js", "/assets/ăpp.js", "/%C0%AE%C0%AE/secret.txt",
    "/assets/./app.js", "/./aplicatie.html", "http://127.0.0.1/aplicatie.html", "aplicatie.html", "*", "/assets/app.js;x=1",
    "/", "/assets", "/assets/", "/interfata/", "/interfata/aplicatie.html", "/index.html", "/.git/config", "/.git/HEAD", "/.env",
]


@pytest.mark.parametrize("target", TRAVERSAL_TARGETS, ids=[target.encode("unicode_escape").decode()[:40] for target in TRAVERSAL_TARGETS])
def test_no_traversal_or_alternate_path_form_reaches_the_disk(app, target):
    """Orice formă de cale în afara adreselor EXACTE din lista albă (`..`, %-codări, `\\`, `//`, nume 8.3, ADS, majuscule, foldere) -> 404 (sau 400 pentru țintă ruptă), niciodată 200 și niciodată conținut secret."""
    status, reply = app.raw_get(target, token=False)
    assert status in (400, 403, 404), f"ținta {target!r} a dat {status}: ar putea citi un fișier din afara listei albe"
    assert MARKER.encode() not in reply, f"ținta {target!r} a scos conținutul secret"


def test_a_leading_double_slash_cannot_reach_anything_but_the_whitelisted_page(app):
    """Biblioteca standard normalizează `//x` la `/x` înainte ca serverul să vadă calea (apărare contra redirecționărilor deschise): rezultatul poate fi doar pagina din lista albă sau 404."""
    for target in ("//aplicatie.html", "//assets/app.js", "//secret.txt", "///assets/app.js", "//evil.example/aplicatie.html"):
        status, reply = app.raw_get(target, token=False)
        assert status in (200, 404) and MARKER.encode() not in reply, f"ținta {target!r} a dat {status}"
        if status == 200:
            assert target.lstrip("/") in ("aplicatie.html", "assets/app.js"), f"ținta {target!r} a servit ceva deși nu e o adresă din lista albă"


def test_the_exact_whitelisted_urls_still_work_over_raw_requests(app):
    """Contra-probă: aceleași cereri brute, dar cu adresele exacte din lista albă, dau 200 (testul de traversare nu pică din cauza clientului)."""
    for target in ("/aplicatie.html", "/assets/app.js", "/assets/app.css", "/aplicatie.html?x=1"):
        assert app.raw_get(target, token=False)[0] == 200, target


def test_the_query_string_is_not_part_of_the_path(app):
    """Query-ul se ignoră, nu ajunge în cale: `/aplicatie.html?../../secret.txt` e tot pagina aplicației."""
    reply = app.call("GET", "/aplicatie.html?x=../../secret.txt", token=False)
    assert reply.status == 200 and MARKER.encode() not in reply.body


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_static_files_answer_only_to_get(app, method):
    """Fișierele statice nu răspund la alte metode decât GET: 405 cu Allow: GET (HEAD inclus, ca un răspuns fără corp să nu ocolească verificările)."""
    reply = app.call(method, "/aplicatie.html", token=False, body=b"{}" if method in ("POST", "PUT", "PATCH") else None)
    assert reply.status == 405 and reply.headers["allow"] == "GET"


def test_the_static_error_page_does_not_echo_the_requested_path(app):
    """Răspunsul 404 nu repetă calea cerută (nicio reflectare de text controlat de cel care cere)."""
    reply = app.call("GET", "/<script>alert(1)</script>", token=False)
    assert reply.status == 404 and b"alert" not in reply.body


# ---------- proiectul real ----------

SENSITIVE_PROJECT_PATHS = [
    "/.git/", "/.git/config", "/.git/HEAD", "/config/", "/config/categorii.json", "/config/categorii.personal.json", "/emag_spend/", "/emag_spend/settings.py",
    "/emag_spend/app_server.py", "/iesiri/", "/iesiri/2026-10-05_09-00-00/analiza.json", "/logs/", "/.profil_browser/", "/.profil_browser/Default/Cookies",
    "/ruleaza.py", "/requirements.txt", "/README.md", "/LICENSE", "/.env", "/.gitignore", "/pytest.ini", "/tests/", "/templates/raport.html",
    "/templates/", "/instaleaza.bat", "/porneste.bat", "/interfata/", "/interfata/assets/dashboard.js", "/assets/comenzi.json", "/comenzi.json",
]


def test_project_files_outside_the_interface_folder_are_never_served(tmp_path):
    """Cu folderul interfata/ REAL al proiectului: /.git/, /config/, /emag_spend/, /iesiri/, /logs/, sesiunea și restul proiectului dau 404."""
    with running_app(tmp_path, interface_dir=INTERFACE_DIR) as app:
        for target in SENSITIVE_PROJECT_PATHS:
            status, _ = app.raw_get(target, token=False)
            assert status in (400, 403, 404), f"{target} a dat {status}: un fișier din proiect (cod, configurare, date sau sesiune) ar putea fi citit din browser"


def test_the_real_whitelist_is_small_html_css_js_only_and_inside_the_interface_folder():
    """Lista albă reală conține doar html/css/js/imagini din interfata/ (nicio dată: .json, .csv, .py), fără demo-data.js decât dacă pagina îl cere."""
    files = app_static.StaticFiles(INTERFACE_DIR)
    root = INTERFACE_DIR.resolve()
    for url in files.urls:
        path = (INTERFACE_DIR / url.lstrip("/")).resolve()
        assert root in path.parents and path.is_file(), f"{url} nu e un fișier din interfata/"
        assert path.suffix in app_static.CONTENT_TYPES, f"{url} are o extensie care nu trebuia servită"
    page = INTERFACE_DIR / "aplicatie.html"
    if page.is_file() and "demo-data" not in page.read_text(encoding="utf-8"):
        assert "/assets/demo-data.js" not in files.urls, "demo-data.js e servit deși pagina aplicației nu îl cere"


# ---------- legături ----------

def test_a_junction_to_an_outside_folder_inside_the_interface_is_not_followed(tmp_path):
    """Dacă `assets` e o joncțiune/legătură spre un folder din afara interfeței, fișierele din ea NU intră în lista albă (resolve iese din interfata/)."""
    outside = tmp_path / "in_afara"
    outside.mkdir()
    (outside / "app.js").write_text(MARKER, encoding="utf-8")
    folder = tmp_path / "interfata"
    folder.mkdir()
    (folder / "aplicatie.html").write_text('<script src="assets/app.js"></script>', encoding="utf-8")
    if not make_directory_link(folder / "assets", outside):
        pytest.skip("sistemul nu permite crearea unei joncțiuni sau legături simbolice de folder")
    assert app_static.StaticFiles(folder).urls == {"/aplicatie.html"}, "un fișier din afara interfeței a intrat în lista albă printr-o legătură"
    with running_app(tmp_path, interface_dir=folder) as app:
        assert app.call("GET", "/assets/app.js", token=False).status == 404


def test_a_file_that_becomes_a_link_after_startup_is_not_read(interface, monkeypatch):
    """Re-verificarea la citire: dacă un fișier din lista albă devine legătură după pornire, `read` întoarce None (nu citește ținta)."""
    files = app_static.StaticFiles(interface)
    assert files.read("/assets/app.js") is not None
    monkeypatch.setattr(app_static, "_is_link_like", lambda path: True)
    assert files.read("/assets/app.js") is None


def test_an_oversized_static_file_is_not_served(interface, monkeypatch):
    """Un fișier static peste limita de mărime nu se servește (404), ca să nu umple memoria."""
    files = app_static.StaticFiles(interface)
    monkeypatch.setattr(app_static, "MAX_STATIC_BYTES", 5)
    assert files.read("/assets/app.js") is None

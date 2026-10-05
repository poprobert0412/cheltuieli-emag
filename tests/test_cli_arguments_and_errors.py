"""Teste pentru linia de comandă: validarea lui --prag, mesajele pentru erorile de browser și --sterge-sesiunea.

Fără browser: `run` se înlocuiește cu o funcție care ridică eroarea dorită. Valorile sunt inventate.
La --sterge-sesiunea profilul de test stă într-un folder temporar; `input` se înlocuiește, deci nu se așteaptă tastatura.
"""

import errno
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

import ruleaza
from emag_spend import session_cleaner, settings


@pytest.mark.parametrize("bad", ["inf", "-inf", "nan", "1e400", "-5", "-0.01", "1e300", "1000000001", "abc", "", "12,5"])
def test_prag_refuses_values_that_would_break_the_report(bad, capsys):
    with pytest.raises(SystemExit) as stop:
        ruleaza._parse_args(["--prag", bad])
    assert stop.value.code == 2
    assert "--prag" in capsys.readouterr().err


@pytest.mark.parametrize("good, expected", [("0", 0.0), ("500", 500.0), ("999.5", 999.5), ("1e3", 1000.0),
                                            (str(settings.MAX_BIG_PURCHASE_THRESHOLD_LEI), float(settings.MAX_BIG_PURCHASE_THRESHOLD_LEI))])
def test_prag_accepts_finite_numbers_inside_the_limits(good, expected):
    assert ruleaza._parse_args(["--prag", good]).prag == expected


def test_prag_error_message_is_in_romanian_and_names_the_limit(capsys):
    with pytest.raises(SystemExit):
        ruleaza._parse_args(["--prag", "inf"])
    error = capsys.readouterr().err
    assert "nu e un prag valid" in error and "1.000.000.000" in error


def test_prag_default_is_the_documented_threshold():
    assert ruleaza._parse_args([]).prag == settings.BIG_PURCHASE_THRESHOLD_LEI


def test_playwright_errors_end_in_a_short_error_line_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")

    def browser_closed(*args, **kwargs):
        raise PlaywrightError("Page.goto: Target page, context or browser has been closed\nCall log:\n  - navigating to https://exemplu.invalid")

    monkeypatch.setattr(ruleaza, "run", browser_closed)
    assert ruleaza.main(["--iesire", str(tmp_path / "out")]) == 1
    output = capsys.readouterr().out
    assert "Traceback" not in output
    summary = output.split("EROARE:", 1)[1]  # blocul final: o singură linie de eroare, apoi calea jurnalului
    assert summary.startswith(" Page.goto: Target page, context or browser has been closed\nJurnal complet:")
    assert "Call log" not in summary
    log_text = next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")
    assert "Call log" in log_text  # jurnalul păstrează tot


# ---------- --sterge-sesiunea și --fara-confirmare ----------

_OTHER_OPTIONS = [["--prag", "600"], ["--limita-comenzi", "5"], ["--din-cache", "x"], ["--iesire", "y"],
                  ["--deschide"], ["--doar-login"], ["--demo"]]


@pytest.mark.parametrize("other", _OTHER_OPTIONS, ids=[option[0] for option in _OTHER_OPTIONS])
def test_sterge_sesiunea_is_exclusive(other, capsys):
    with pytest.raises(SystemExit) as stop:
        ruleaza._parse_args(["--sterge-sesiunea", *other])
    assert stop.value.code == 2
    error = capsys.readouterr().err
    assert "--sterge-sesiunea nu se combină cu" in error and other[0] in error


def test_sterge_sesiunea_accepts_only_fara_confirmare_beside_it():
    args = ruleaza._parse_args(["--sterge-sesiunea", "--fara-confirmare"])
    assert args.sterge_sesiunea and args.fara_confirmare
    assert ruleaza._parse_args(["--sterge-sesiunea"]).fara_confirmare is False


def test_fara_confirmare_alone_is_refused(capsys):
    with pytest.raises(SystemExit) as stop:
        ruleaza._parse_args(["--fara-confirmare"])
    assert stop.value.code == 2
    assert "--fara-confirmare se folosește doar împreună cu --sterge-sesiunea" in capsys.readouterr().err


def test_an_explicit_prag_equal_to_the_default_still_counts_as_given(capsys):
    """Verificarea de exclusivitate se uită la ce a scris utilizatorul, nu la valoarea rezultată."""
    with pytest.raises(SystemExit):
        ruleaza._parse_args(["--sterge-sesiunea", "--prag", str(settings.BIG_PURCHASE_THRESHOLD_LEI)])
    assert "--prag" in capsys.readouterr().err


@pytest.fixture
def saved_session(tmp_path, monkeypatch):
    """Un profil Chromium inventat în folder temporar, pus ca profil al programului; browserul și raportul pică testul."""
    def forbidden(*args, **kwargs):
        raise AssertionError("--sterge-sesiunea nu are voie să pornească browserul sau un raport")

    profile = tmp_path / "profil_browser"
    (profile / "Default").mkdir(parents=True)
    (profile / "Local State").write_text("{}", encoding="utf-8")
    (profile / "Default" / "Cookies").write_bytes(b"cookie-inventat")
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(settings, "PROFILE_DIR", profile)
    monkeypatch.setattr(ruleaza, "run", forbidden)
    monkeypatch.setattr(ruleaza, "login_only", forbidden)
    return profile


def _answer(monkeypatch, reply):
    """Înlocuiește input(): `reply` e textul tastat sau o excepție ridicată (EOF, Ctrl+C)."""
    def fake_input(prompt=""):
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr("builtins.input", fake_input)


def test_typing_exactly_da_deletes_the_session(saved_session, monkeypatch, capsys):
    _answer(monkeypatch, "DA")
    assert ruleaza.main(["--sterge-sesiunea"]) == 0
    output = capsys.readouterr().out
    assert not saved_session.exists()
    assert "Sesiunea eMAG salvată a fost ștearsă" in output and str(saved_session.resolve()) in output
    assert "Pentru a invalida orice sesiune veche poți schimba parola eMAG" in output


@pytest.mark.parametrize("reply", ["da", "nu", "", "DA, sigur", EOFError(), KeyboardInterrupt()],
                         ids=["da-mic", "nu", "gol", "text-in-plus", "eof", "ctrl-c"])
def test_anything_but_exactly_da_cancels_and_deletes_nothing(saved_session, monkeypatch, capsys, reply):
    _answer(monkeypatch, reply)
    assert ruleaza.main(["--sterge-sesiunea"]) == 0  # anularea nu e o eroare
    assert "Anulat: nu am șters nimic" in capsys.readouterr().out
    assert (saved_session / "Default" / "Cookies").is_file()


def test_the_confirmation_shows_the_full_path_before_asking(saved_session, monkeypatch, capsys):
    _answer(monkeypatch, "nu")
    ruleaza.main(["--sterge-sesiunea"])
    assert str(saved_session.resolve()) in capsys.readouterr().out


def test_fara_confirmare_deletes_without_asking(saved_session, monkeypatch, capsys):
    def no_question(prompt=""):
        raise AssertionError("cu --fara-confirmare nu se întreabă nimic")

    monkeypatch.setattr("builtins.input", no_question)
    assert ruleaza.main(["--sterge-sesiunea", "--fara-confirmare"]) == 0
    assert not saved_session.exists() and "a fost ștearsă" in capsys.readouterr().out


def test_no_saved_session_is_not_an_error(saved_session, monkeypatch, capsys):
    monkeypatch.setattr(settings, "PROFILE_DIR", saved_session.parent / "nu_exista")
    assert ruleaza.main(["--sterge-sesiunea", "--fara-confirmare"]) == 0
    assert "Nu există nicio sesiune salvată" in capsys.readouterr().out


def test_a_folder_that_does_not_look_like_a_browser_profile_is_refused_with_exit_code_1(tmp_path, saved_session, monkeypatch, capsys):
    documents = tmp_path / "documente"
    documents.mkdir()
    (documents / "raport.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings, "PROFILE_DIR", documents)  # ca și cum EMAG_PROFILE_DIR ar fi setat greșit
    assert ruleaza.main(["--sterge-sesiunea", "--fara-confirmare"]) == 1
    output = capsys.readouterr().out
    assert "EROARE: nu am șters nimic" in output and "EMAG_PROFILE_DIR" in output and "Traceback" not in output
    assert (documents / "raport.txt").is_file()


def test_locked_files_end_in_exit_code_1_with_the_romanian_hint_and_no_traceback(saved_session, monkeypatch, capsys):
    real_delete = session_cleaner._delete_file

    def locked_cookies(path):
        if Path(path).name == "Cookies":
            raise PermissionError(errno.EACCES, "folosit de alt program")
        real_delete(path)

    monkeypatch.setattr(session_cleaner, "_delete_file", locked_cookies)
    assert ruleaza.main(["--sterge-sesiunea", "--fara-confirmare"]) == 1
    output = capsys.readouterr().out
    assert "Închide fereastra Edge deschisă de program și rulează din nou" in output and "Traceback" not in output
    assert (saved_session / "Default" / "Cookies").is_file() and not (saved_session / "Local State").exists()  # ștergere parțială, raportată


def test_the_deletion_leaves_a_line_in_the_log(saved_session, tmp_path):
    assert ruleaza.main(["--sterge-sesiunea", "--fara-confirmare"]) == 0
    log_text = next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")
    assert "ștergere sesiune: deleted" in log_text


# ---------- --aplicatie și --fara-browser ----------

_OTHER_OPTIONS_FOR_APP = [["--prag", "600"], ["--limita-comenzi", "5"], ["--din-cache", "x"], ["--iesire", "y"],
                          ["--deschide"], ["--doar-login"], ["--demo"]]


@pytest.mark.parametrize("other", _OTHER_OPTIONS_FOR_APP, ids=[option[0] for option in _OTHER_OPTIONS_FOR_APP])
def test_aplicatie_is_exclusive_like_demo(other, capsys):
    """--aplicatie pornește un server: nu se combină cu opțiunile care citesc contul sau fac un raport; mesajul în română numește opțiunea în plus."""
    with pytest.raises(SystemExit) as stop:
        ruleaza._parse_args(["--aplicatie", *other])
    assert stop.value.code == 2
    error = capsys.readouterr().err
    assert "--aplicatie nu se combină cu" in error and other[0] in error and "doar cu --fara-browser" in error


def test_aplicatie_and_sterge_sesiunea_cannot_be_combined(capsys):
    """--sterge-sesiunea (distructivă) nu se amestecă cu --aplicatie, în niciuna din ordini."""
    for argv in (["--sterge-sesiunea", "--aplicatie"], ["--aplicatie", "--sterge-sesiunea"]):
        with pytest.raises(SystemExit) as stop:
            ruleaza._parse_args(argv)
        assert stop.value.code == 2
        assert "nu se combină cu" in capsys.readouterr().err


def test_aplicatie_accepts_only_fara_browser_beside_it():
    """--aplicatie merge singură sau cu --fara-browser; fără --aplicatie, --fara-browser e refuzat."""
    assert ruleaza._parse_args(["--aplicatie"]).aplicatie and not ruleaza._parse_args(["--aplicatie"]).fara_browser
    args = ruleaza._parse_args(["--aplicatie", "--fara-browser"])
    assert args.aplicatie and args.fara_browser


def test_fara_browser_alone_is_refused(capsys):
    """--fara-browser nu are sens fără --aplicatie: eroare clară în română."""
    with pytest.raises(SystemExit) as stop:
        ruleaza._parse_args(["--fara-browser"])
    assert stop.value.code == 2
    assert "--fara-browser se folosește doar împreună cu --aplicatie" in capsys.readouterr().err


class FakeAppServer:
    """Server fals pentru testele CLI: notează ce se cere și oprește imediat cu motivul dat."""

    created: list["FakeAppServer"] = []
    reason = "shutdown"
    fail_with: Exception | None = None
    serve_error: Exception | None = None
    idle_minutes = 30

    def __init__(self, **kwargs):
        if self.fail_with:
            raise self.fail_with
        self.kwargs = kwargs
        self.marker = "valoare-inventata-pentru-teste-0123456789"
        self.port = 40123
        self.closed = False
        self.served = False
        FakeAppServer.created.append(self)

    def page_url(self, with_token=False):
        base = "http://127.0.0.1:%d/aplicatie.html" % self.port
        return base + ("#t=" + self.marker if with_token else "")

    def serve(self):
        self.served = True
        if self.serve_error:
            raise self.serve_error
        return self.reason

    def close(self):
        self.closed = True


@pytest.fixture
def fake_app(tmp_path, monkeypatch):
    """Înlocuiește serverul și deschiderea browserului; jurnalul merge în folder temporar și handler-ele rădăcinii se restaurează."""
    from emag_spend.app_opener import OpenResult
    from tests.garda_audit import isolated_program

    FakeAppServer.created = []
    FakeAppServer.reason = "shutdown"
    FakeAppServer.fail_with = None
    FakeAppServer.serve_error = None
    opened = []
    monkeypatch.setattr(ruleaza, "AppServer", FakeAppServer)
    monkeypatch.setattr(ruleaza, "open_app_page", lambda url: opened.append(url) or OpenResult(True))
    with isolated_program(monkeypatch, tmp_path) as layout:
        layout.app_opened = opened
        yield layout


def test_aplicatie_opens_the_browser_and_prints_the_url_without_the_token(fake_app, capsys):
    """Fără --fara-browser: browserul primește adresa cu token, consola arată adresa FĂRĂ token și instrucțiunile în română; ieșire 0."""
    assert ruleaza.main(["--aplicatie"]) == 0
    output = capsys.readouterr().out
    (server,) = FakeAppServer.created
    assert fake_app.app_opened == [server.page_url(with_token=True)] and server.served and server.closed
    assert server.page_url() in output and server.marker not in output and "#t=" not in output, "tokenul a ajuns pe ecran"
    assert "Pagina s-a deschis în browserul tău" in output and "Ctrl+C" in output and "Închide aplicația" in output
    assert "30 de minute fără activitate" in output and "Aplicația a fost închisă din pagină." in output
    assert "Traceback" not in output


def test_aplicatie_passes_the_session_log_path_to_the_server(fake_app, capsys):
    """Serverul primește calea jurnalului sesiunii (ajunge în run_info.json al rulărilor din aplicație)."""
    ruleaza.main(["--aplicatie"])
    (server,) = FakeAppServer.created
    assert server.kwargs["log_path"] is not None and server.kwargs["log_path"].parent == fake_app.logs and server.kwargs["log_path"].suffix == ".log"


def test_aplicatie_fara_browser_prints_the_full_url_and_opens_nothing(fake_app, capsys):
    """Cu --fara-browser nu se deschide nimic și URL-ul COMPLET (cu token) apare în consolă, pentru teste, WSL și servere."""
    assert ruleaza.main(["--aplicatie", "--fara-browser"]) == 0
    output = capsys.readouterr().out
    (server,) = FakeAppServer.created
    assert fake_app.app_opened == [] and fake_app.opened == []
    assert server.page_url(with_token=True) in output and "cu cheia de acces" in output


def test_aplicatie_tells_the_url_and_why_when_the_browser_cannot_be_opened(fake_app, monkeypatch, capsys):
    """Dacă deschiderea browserului eșuează: se scrie motivul și adresa completă, ca utilizatorul s-o deschidă singur; nu e eroare (cod 0)."""
    from emag_spend.app_opener import OpenResult

    monkeypatch.setattr(ruleaza, "open_app_page", lambda url: OpenResult(False, "sistemul nu are un browser implicit configurat"))
    assert ruleaza.main(["--aplicatie"]) == 0
    output = capsys.readouterr().out
    (server,) = FakeAppServer.created
    assert "Nu am putut deschide browserul automat (sistemul nu are un browser implicit configurat)" in output
    assert server.page_url(with_token=True) in output and server.served


@pytest.mark.parametrize("reason, text", [("shutdown", "închisă din pagină"), ("idle", "s-a oprit singură"), ("interrupted", "oprită cu Ctrl+C"), ("altceva", "Aplicația s-a oprit.")])
def test_aplicatie_says_why_it_stopped(fake_app, capsys, reason, text):
    """La oprire, mesajul spune motivul (buton, inactivitate, Ctrl+C), iar un motiv necunoscut primește mesajul general; toate ies cu 0."""
    FakeAppServer.reason = reason
    assert ruleaza.main(["--aplicatie", "--fara-browser"]) == 0
    assert text in capsys.readouterr().out


@pytest.mark.parametrize("error", [OSError("adresa nu poate fi legată"), ValueError("variabila EMAG_APP_IDLE_MINUTES trebuie să fie un număr")], ids=["OSError", "ValueError"])
def test_aplicatie_start_errors_end_in_a_romanian_error_line_without_traceback(fake_app, capsys, error):
    """Dacă serverul nu poate porni (legare eșuată, variabilă de mediu greșită): EROARE în română, fără traceback, ieșire 1; nu se deschide nimic."""
    FakeAppServer.fail_with = error
    assert ruleaza.main(["--aplicatie"]) == 1
    output = capsys.readouterr().out
    assert "EROARE: nu am putut porni aplicația locală" in output and str(error) in output and "Traceback" not in output
    assert fake_app.app_opened == []


def test_aplicatie_closes_the_server_even_when_serving_blows_up(fake_app):
    """Chiar dacă `serve` ridică o excepție neprevăzută, socket-ul se închide (finally): nu rămâne un port deschis."""
    FakeAppServer.serve_error = RuntimeError("defect neprevăzut")
    with pytest.raises(RuntimeError):
        ruleaza.main(["--aplicatie", "--fara-browser"])
    assert FakeAppServer.created[0].closed


def test_the_token_never_reaches_the_log_file_when_starting_the_application(fake_app, capsys):
    """Jurnalul din logs/ nu conține tokenul (adresa cu token se scrie doar cu print, nu prin logger), în niciuna din variantele de pornire."""
    ruleaza.main(["--aplicatie"])
    ruleaza.main(["--aplicatie", "--fara-browser"])
    logs = list(fake_app.logs.glob("*.log"))
    assert logs, "nu s-a scris niciun jurnal: testul nu dovedește nimic"
    assert all(FakeAppServer.created[0].marker not in log.read_text(encoding="utf-8") for log in logs)


@pytest.mark.parametrize("minutes, text", [(1, "1 minut"), (2, "2 minute"), (15, "15 minute"), (19, "19 minute"), (20, "20 de minute"), (30, "30 de minute"),
                                           (101, "101 minute"), (120, "120 de minute"), (1440, "1440 de minute"), (1.5, "1.5 minute")])
def test_the_idle_time_is_written_with_correct_romanian_agreement(minutes, text):
    """«1 minut», «15 minute», «30 de minute»: acordul numărului cu «minute» în mesajul de pornire."""
    assert ruleaza._minutes_text(minutes) == text

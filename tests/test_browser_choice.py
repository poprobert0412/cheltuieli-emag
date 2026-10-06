"""Alegerea browserului pe orice sistem: Edge, apoi Chrome, apoi Chromium-ul descărcat de lansatoare.

Primește: browser_session cu un `chromium` fals (fără browser real) și app_errors. Verifică: ordinea implicită, alegerea
din EMAG_BROWSER_CHANNEL, trecerea la următorul browser DOAR când cel încercat lipsește, eroarea clară când lipsesc toate,
oprirea imediată la alte erori (profil deschis) și mesajul în română al aplicației. Nu pornește niciun browser.
"""

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError

from emag_spend import app_errors, browser_session, settings


class FakeChromium:
    """`playwright.chromium` fals: pentru fiecare browser întoarce un context sau ridică eroarea dată în `outcomes`."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    async def launch_persistent_context(self, profile_dir, **kwargs):
        """Notează încercarea și întoarce rezultatul stabilit pentru browserul cerut (fără channel = Chromium descărcat)."""
        channel = kwargs.get("channel", settings.DOWNLOADED_BROWSER)
        self.calls.append((channel, kwargs))
        outcome = self.outcomes[channel]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def missing(name):
    """Eroarea Playwright pentru un browser care nu e instalat (forma mesajului real)."""
    return PlaywrightError(f"Chromium distribution '{name}' is not found at /opt/{name}\nRun \"playwright install {name}\"")


def tried(fake):
    """Browserele încercate, în ordine."""
    return [channel for channel, _ in fake.calls]


def test_default_order_is_edge_then_chrome_then_downloaded_chromium(monkeypatch):
    """Fără EMAG_BROWSER_CHANNEL: Edge (există pe orice Windows 10/11), Chrome, apoi Chromium descărcat."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", None)
    assert browser_session.browser_candidates() == ("msedge", "chrome", "chromium")


def test_a_browser_chosen_in_the_environment_is_the_only_candidate(monkeypatch):
    """Cu EMAG_BROWSER_CHANNEL=chrome se încearcă doar Chrome: utilizatorul a ales explicit."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", "chrome")
    assert browser_session.browser_candidates() == ("chrome",)


def test_downloaded_chromium_starts_without_a_channel():
    """Chromium-ul descărcat de Playwright se pornește fără `channel`; celelalte cu numele lor."""
    assert browser_session.launch_options("chromium") == {}
    assert browser_session.launch_options("msedge") == {"channel": "msedge"}
    assert browser_session.launch_options("chrome") == {"channel": "chrome"}


def test_missing_edge_falls_back_to_chrome_with_a_visible_window(monkeypatch, tmp_path):
    """Pe un Mac sau Linux fără Edge: se trece la Chrome, iar fereastra rămâne vizibilă (login-ul îl face omul)."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", None)
    fake = FakeChromium({"msedge": missing("msedge"), "chrome": "CONTEXT-CHROME", "chromium": "NU-AJUNGE-AICI"})
    context, used = asyncio.run(browser_session.launch_first_available(fake, tmp_path))
    assert (context, used) == ("CONTEXT-CHROME", "chrome")
    assert tried(fake) == ["msedge", "chrome"]
    assert all(kwargs["headless"] is False and kwargs["no_viewport"] is True for _, kwargs in fake.calls)


def test_only_the_downloaded_chromium_is_left(monkeypatch, tmp_path):
    """Fără Edge și fără Chrome: se folosește Chromium-ul descărcat de lansator."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", None)
    fake = FakeChromium({"msedge": missing("msedge"), "chrome": missing("chrome"), "chromium": "CONTEXT-CHROMIUM"})
    assert asyncio.run(browser_session.launch_first_available(fake, tmp_path)) == ("CONTEXT-CHROMIUM", "chromium")


def test_no_installed_browser_raises_a_clear_error_naming_what_was_tried(monkeypatch, tmp_path):
    """Când nu e instalat niciunul: NoBrowserFound, cu lista încercată (nu o eroare Playwright criptică)."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", None)
    fake = FakeChromium({name: missing(name) for name in ("msedge", "chrome", "chromium")})
    with pytest.raises(browser_session.NoBrowserFound) as caught:
        asyncio.run(browser_session.launch_first_available(fake, tmp_path))
    assert "msedge, chrome, chromium" in str(caught.value)


def test_other_launch_errors_stop_at_once_instead_of_trying_another_browser(monkeypatch, tmp_path):
    """Profilul deja deschis în altă fereastră nu e „browser lipsă”: eroarea se raportează imediat, fără alt browser."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", None)
    busy = PlaywrightError("Failed to create a ProcessSingleton for your profile directory")
    fake = FakeChromium({"msedge": busy, "chrome": "NU-AJUNGE-AICI", "chromium": "NU-AJUNGE-AICI"})
    with pytest.raises(browser_session.BrowserLaunchFailed) as caught:
        asyncio.run(browser_session.launch_first_available(fake, tmp_path))
    assert not isinstance(caught.value, browser_session.NoBrowserFound)
    assert tried(fake) == ["msedge"]


def test_application_explains_what_to_do_when_no_browser_is_found(monkeypatch):
    """Mesajul aplicației spune ce faci pe orice sistem: instalezi Edge/Chrome sau folosești lansatorul care aduce Chromium."""
    monkeypatch.setattr(settings, "BROWSER_CHANNEL", None)
    result = app_errors.classify_error(browser_session.NoBrowserFound("nu găsesc niciun browser instalat dintre: msedge"))
    assert result.code == app_errors.CODE_BROWSER_MISSING
    for needed in ("Edge", "Chrome", "porneste.bat", "porneste.command", "porneste.sh"):
        assert needed in result.message, needed

"""Transformă o excepție a rulării într-un cod stabil și un mesaj în română, cu „ce faci”, pentru API-ul aplicației.

Primește: excepția ridicată de pipeline (în firul de fundal al aplicației). Dă înapoi: RunError(code, message).
Codurile sunt stabile, interfața se bazează pe ele: login_timeout, session_expired, browser_missing, profile_in_use, unexpected.
Tipurile proprii (LoginTimeout, SessionExpired, BrowserLaunchFailed) se recunosc direct; Playwright nu are tipuri
separate pentru „browser lipsă” sau „profil deja deschis”, deci acolo se caută fragmente din mesajul lui (euristică,
validată doar pe mesaje scrise după documentația Playwright; orice nu se potrivește ajunge la `unexpected`, cu detaliul).
Ce NU face: nu decide starea rulării (app_runner.py) și nu scrie în jurnal.
"""

from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError

from emag_spend import settings
from emag_spend.browser_session import BrowserLaunchFailed, LoginTimeout
from emag_spend.page_fetcher import SessionExpired

CODE_LOGIN_TIMEOUT = "login_timeout"
CODE_SESSION_EXPIRED = "session_expired"
CODE_BROWSER_MISSING = "browser_missing"
CODE_PROFILE_IN_USE = "profile_in_use"
CODE_UNEXPECTED = "unexpected"
ERROR_CODES = (CODE_LOGIN_TIMEOUT, CODE_SESSION_EXPIRED, CODE_BROWSER_MISSING, CODE_PROFILE_IN_USE, CODE_UNEXPECTED)

# Fragmente (cu litere mici) din mesajele Playwright când browserul ales nu e instalat.
BROWSER_MISSING_MARKERS = ("is not found at", "executable doesn't exist", "playwright install")
# Fragmente când profilul programului e deja deschis într-o fereastră Edge/Chrome: Chromium cedează procesului vechi și iese,
# deci Playwright vede „browser închis” chiar la pornire.
PROFILE_IN_USE_MARKERS = ("existing browser session", "processsingleton", "singletonlock", "already in use", "has been closed", "browser closed")
# Fragmente când utilizatorul (sau altceva) a închis fereastra browserului DUPĂ pornire.
BROWSER_CLOSED_MARKERS = ("has been closed", "target closed", "browser closed")
# Cât din mesajul excepției se arată utilizatorului: destul cât să fie util, prea puțin ca să umple ecranul cu un „Call log”.
MAX_DETAIL_CHARS = 300
# Excepțiile cu mesaj scris pentru oameni (în română sau de la sistem); la celelalte (KeyError, TypeError...) arătăm doar tipul.
HUMAN_MESSAGE_ERRORS = (RuntimeError, ValueError, OSError, PlaywrightError)


@dataclass(frozen=True)
class RunError:
    """Eroarea unei rulări, gata de arătat: cod stabil + mesaj în română (ce s-a întâmplat și ce faci)."""

    code: str
    message: str


def _wait_text() -> str:
    """Cât așteaptă programul login-ul, în cuvinte (din settings.LOGIN_WAIT_SECONDS)."""
    seconds = settings.LOGIN_WAIT_SECONDS
    return f"{seconds // 60} minute" if seconds % 60 == 0 else f"{seconds} de secunde"


def _first_line(error: BaseException) -> str:
    """Prima linie a mesajului excepției, tăiată la MAX_DETAIL_CHARS (restul, ex. „Call log” de la Playwright, rămâne în jurnal)."""
    text = str(error).strip().splitlines()[0] if str(error).strip() else ""
    return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS].rstrip() + "…"


def classify_error(error: BaseException) -> RunError:
    """Codul și mesajul în română pentru `error`; nu ridică excepții și nu întoarce niciodată un mesaj gol."""
    if isinstance(error, LoginTimeout):
        return RunError(CODE_LOGIN_TIMEOUT, (
            f"Nu te-ai logat în cele {_wait_text()} alocate. "
            "Ce faci: apasă din nou «Pornește analiza» și loghează-te în fereastra de browser care se deschide."
        ))
    if isinstance(error, SessionExpired):
        return RunError(CODE_SESSION_EXPIRED, (
            "Sesiunea eMAG a expirat în timpul citirii. "
            "Ce faci: apasă din nou «Pornește analiza» și loghează-te când se deschide fereastra browserului."
        ))
    lowered = str(error).lower()
    if isinstance(error, PlaywrightError) and any(marker in lowered for marker in BROWSER_MISSING_MARKERS):
        return RunError(CODE_BROWSER_MISSING, (
            f"Nu găsesc browserul «{settings.BROWSER_CHANNEL}» pe acest calculator. "
            "Ce faci: instalează Microsoft Edge (sau Google Chrome și pornește programul cu variabila de mediu "
            "EMAG_BROWSER_CHANNEL=chrome), apoi apasă din nou «Pornește analiza»."
        ))
    if isinstance(error, BrowserLaunchFailed) and any(marker in lowered for marker in PROFILE_IN_USE_MARKERS):
        return RunError(CODE_PROFILE_IN_USE, (
            "Profilul de browser al programului este deja deschis într-o altă fereastră. "
            "Ce faci: închide ferestrele Edge deschise de program (și orice altă copie a programului), "
            "apoi apasă din nou «Pornește analiza»."
        ))
    if isinstance(error, PlaywrightError) and any(marker in lowered for marker in BROWSER_CLOSED_MARKERS):
        return RunError(CODE_UNEXPECTED, (
            "Fereastra browserului s-a închis înainte să se termine citirea. "
            "Ce faci: nu închide fereastra deschisă de program până nu se termină; apasă din nou «Pornește analiza»."
        ))
    detail = _first_line(error) if isinstance(error, HUMAN_MESSAGE_ERRORS) else type(error).__name__
    return RunError(CODE_UNEXPECTED, (
        f"A apărut o eroare neașteptată ({detail or type(error).__name__}). "
        "Ce faci: încearcă din nou; dacă se repetă, citește jurnalul din folderul logs (poate conține numere de comenzi: "
        "nu îl trimite nimănui fără să-l citești)."
    ))

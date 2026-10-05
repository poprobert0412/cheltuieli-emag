"""Deschide un browser cu sesiunea ta eMAG și așteaptă să fii logat.

Primește: setările (profil, browser, timp de așteptare) și, opțional, un raportor de progres (progress.py). Dă înapoi: contextul Playwright logat (pentru celelalte module).
Login-ul îl faci TU, manual, în fereastra deschisă: parola și codul 2FA nu trec prin acest program, care NU tastează și NU apasă nimic în paginile eMAG. Singura adresă pe care o deschide programul aici e settings.BASE_URL (istoricul de comenzi).
Sesiunea rămâne în folderul profilului (.profil_browser), deci la rulările următoare nu mai e nevoie de login cât timp eMAG n-o expiră. La anulare sau la orice eroare browserul se închide prin `finally`.
Nu citește comenzi și nu calculează nimic."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from playwright.async_api import Error as PlaywrightError

from emag_spend import settings
from emag_spend.progress import NO_PROGRESS, PHASE_WAITING_LOGIN, Progress

logger = logging.getLogger(__name__)


class LoginTimeout(RuntimeError):
    """Utilizatorul nu s-a logat în timpul alocat (settings.LOGIN_WAIT_SECONDS); un tip propriu ca aplicația locală să-l recunoască fără să citească mesajul."""


class BrowserLaunchFailed(PlaywrightError):
    """Browserul n-a putut fi pornit (lipsește sau profilul e deja deschis în altă fereastră).

    E tot o eroare Playwright, cu exact același mesaj: linia de comandă o tratează ca înainte, iar aplicația locală
    știe că eșecul a venit de la pornire (nu de la o pagină închisă de utilizator în timpul rulării) și îl poate explica.
    """


async def _is_logged_in(page) -> bool:
    """True dacă pagina curentă e o pagină de cont (are "Comenzile mele" și "Log out")."""
    try:
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:  # pagina se reîncarcă în timpul redirecționării
        return False
    return "Comenzile mele" in text and "Log out" in text


async def ensure_logged_in(page, wait_seconds: int = settings.LOGIN_WAIT_SECONDS, progress: Progress = NO_PROGRESS) -> None:
    """Deschide istoricul de comenzi și, dacă nu ești logat, așteaptă să te loghezi.

    Ridică LoginTimeout (un RuntimeError) dacă nu te loghezi în `wait_seconds` și RunCancelled dacă utilizatorul
    oprește rularea cât așteaptă login-ul (verificat la fiecare interogare, deci în cel mult LOGIN_POLL_SECONDS).
    """
    progress.raise_if_cancelled()
    url = settings.BASE_URL + settings.ORDER_LIST_FIRST_PAGE_PATH
    await page.goto(url, wait_until="domcontentloaded")
    if await _is_logged_in(page):
        logger.info("sesiune eMAG activă, nu e nevoie de login")
        return
    message = (
        "Loghează-te în fereastra de browser care s-a deschis (parola și codul 2FA le "
        f"introduci tu). Aștept până la {wait_seconds // 60} minute."
    )
    logger.info(message)
    print(f"\n>>> {message}\n", flush=True)
    progress.phase(PHASE_WAITING_LOGIN)
    progress.message(message)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(settings.LOGIN_POLL_SECONDS)
        progress.raise_if_cancelled()
        if await _is_logged_in(page):
            logger.info("login reușit")
            await page.goto(url, wait_until="domcontentloaded")
            return
    raise LoginTimeout("nu te-ai logat în timpul alocat; rulează din nou scriptul")


async def login_only() -> None:
    """Deschide browserul, așteaptă login-ul și îl închide: sesiunea rămâne salvată în profil."""
    async with logged_in_browser():
        logger.info("sesiune salvată în %s", settings.PROFILE_DIR)


@asynccontextmanager
async def logged_in_browser(progress: Progress = NO_PROGRESS):
    """Context async: deschide browserul cu profilul salvat, asigură login-ul, apoi îl închide.

    Folosire: `async with logged_in_browser() as (context, page): ...`
    O eroare la PORNIREA browserului (ridicată ca BrowserLaunchFailed, același mesaj Playwright) se deosebește de
    una de mai târziu; după pornire, `finally` închide contextul și la eroare, și la anulare.
    """
    from playwright.async_api import async_playwright  # import târziu: testele nu au nevoie de browser

    settings.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(settings.PROFILE_DIR),
                channel=settings.BROWSER_CHANNEL,
                headless=False,
                no_viewport=True,
            )
        except PlaywrightError as error:
            raise BrowserLaunchFailed(str(error)) from error
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await ensure_logged_in(page, progress=progress)
            yield context, page
        finally:
            await context.close()

"""Strânge adresele paginilor de detalii ale tuturor retururilor din cont.

Primește: o pagină de browser logată și, opțional, un raportor de progres (progress.py). Dă înapoi: lista căilor de forma "/user/return-history/<x>/<număr retur>", fără duplicate.
Lista de retururi se încarcă pe bucăți: se apasă "Vezi mai mult" până nu mai apare butonul sau nu se mai adaugă nimic; se oprește cooperant când utilizatorul cere.
Un cont fără niciun retur nu are nicio legătură de așteptat: după timpul de randare, dacă pagina e încă lista de retururi, rezultatul e o listă goală (cu avertisment în jurnal); dacă eMAG a redirecționat la login, rularea se oprește ca la sesiune expirată.
Nu descarcă detaliile returului."""

import asyncio
import logging
import time

from playwright.async_api import TimeoutError as PlaywrightTimeout

from emag_spend import settings
from emag_spend.page_fetcher import SessionExpired
from emag_spend.progress import NO_PROGRESS, Progress

logger = logging.getLogger(__name__)

_LINKS_JS = """() => [...new Set([...document.querySelectorAll('a[href*="/user/return-history/"]')]
  .map(a => new URL(a.href, location.href).pathname))]
  .filter(p => /\\/user\\/return-history\\/\\d+\\/\\d+$/.test(p))"""

_LOAD_MORE_SELECTOR = ".js-return-history-view-more"
_GROW_TIMEOUT_SECONDS = 15


async def _wait_for_growth(page, before: int, progress: Progress = NO_PROGRESS) -> int:
    """Așteaptă să crească numărul de retururi față de `before`; întoarce numărul nou (oprirea cerută se verifică la fiecare citire)."""
    deadline = time.monotonic() + _GROW_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        progress.raise_if_cancelled()
        count = len(await page.evaluate(_LINKS_JS))
        if count > before:
            return count
        await asyncio.sleep(0.5)
    return before


async def collect_return_paths(page, progress: Progress = NO_PROGRESS) -> list[str]:
    """Căile paginilor de detalii pentru toate retururile ([] la un cont fără retururi).

    Ridică SessionExpired dacă după așteptare pagina e cea de login (nu o listă goală).
    """
    progress.raise_if_cancelled()
    await page.goto(settings.BASE_URL + settings.RETURN_LIST_PATH, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("a[href*='/user/return-history/']", timeout=settings.LIST_RENDER_TIMEOUT_SECONDS * 1000)
    except PlaywrightTimeout:
        # Fără linkuri: ori contul nu are retururi, ori sesiunea a expirat. Redirectul la login se vede în adresă.
        if "login" in page.url.lower():
            raise SessionExpired("redirecționat la login la lista de retururi") from None
        logger.warning(
            "lista de retururi: niciun retur găsit în %ds; contul nu are retururi sau pagina s-a schimbat "
            "(verifică în cont dacă ai retururi)", settings.LIST_RENDER_TIMEOUT_SECONDS,
        )
        return []
    count = len(await page.evaluate(_LINKS_JS))
    for _ in range(settings.MAX_RETURN_LOAD_MORE_CLICKS):
        progress.raise_if_cancelled()
        progress.message(f"Caut retururile în cont: {count} găsite până acum")
        button = page.locator(_LOAD_MORE_SELECTOR)
        if await button.count() == 0 or not await button.first.is_visible():
            break
        await button.first.click()
        grown = await _wait_for_growth(page, count, progress)
        if grown == count:
            break
        count = grown
    paths = await page.evaluate(_LINKS_JS)
    logger.info("lista de retururi: %d retururi", len(paths))
    return paths

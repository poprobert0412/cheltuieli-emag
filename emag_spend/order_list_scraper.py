"""Strânge numerele tuturor comenzilor din lista paginată din contul eMAG.

Primește: o pagină de browser logată și, opțional, un raportor de progres (progress.py). Dă înapoi: lista numerelor de comandă, fără duplicate, în ordinea din listă (cele mai noi primele).
Lista e randată de JavaScript, deci se așteaptă să se încarce comenzile reale (nu cele 3 schelete cu număr 000000000).
Dacă apare o comandă nouă în timpul parcurgerii, paginile se deplasează cu o poziție și unele numere apar de două ori; duplicatele sunt eliminate, nu se pierde nicio comandă.
Se oprește cooperant când utilizatorul cere (între pagini și în așteptarea randării). Nu descarcă detaliile comenzilor."""

import asyncio
import logging
import time

from emag_spend import settings
from emag_spend.progress import NO_PROGRESS, Progress

logger = logging.getLogger(__name__)

_READ_IDS_JS = """() => {
  const ids = [...document.querySelectorAll('a[href*="/history/shoppingdetails/"]')]
    .map(a => (a.getAttribute('href').match(/shoppingdetails\\/(\\d+)/) || [])[1])
    .filter(Boolean);
  return [...new Set(ids)];
}"""

_LAST_PAGE_JS = """() => {
  const nums = [...document.querySelectorAll('[class*="pagination"] *')]
    .filter(e => e.children.length === 0)
    .map(e => e.textContent.trim()).filter(t => /^\\d+$/.test(t)).map(Number);
  return nums.length ? Math.max(...nums) : 1;
}"""

_PLACEHOLDER_ID = "0" * 9


async def _read_rendered_ids(page, progress: Progress = NO_PROGRESS) -> list[str]:
    """Numerele de comandă după ce lista s-a randat complet (stabil două citiri la rând).

    Oprirea cerută de utilizator se verifică la fiecare citire (cel mult ~0,7 s întârziere).
    """
    deadline = time.monotonic() + settings.LIST_RENDER_TIMEOUT_SECONDS
    previous: list[str] | None = None
    while True:
        progress.raise_if_cancelled()
        ids = await page.evaluate(_READ_IDS_JS)
        real = [i for i in ids if i != _PLACEHOLDER_ID]
        if real and len(real) == len(ids) and real == previous:
            return real
        previous = real
        if time.monotonic() > deadline:
            return real
        await asyncio.sleep(0.7)


async def _open_list_page(page, page_no: int, progress: Progress = NO_PROGRESS) -> list[str]:
    """Deschide pagina `page_no` din listă și întoarce comenzile ei."""
    path = (
        settings.ORDER_LIST_FIRST_PAGE_PATH
        if page_no == 1
        else settings.ORDER_LIST_PAGE_PATH.format(page=page_no)
    )
    await page.goto(settings.BASE_URL + path, wait_until="domcontentloaded")
    return await _read_rendered_ids(page, progress)


async def collect_order_ids(page, max_orders: int | None = None, progress: Progress = NO_PROGRESS) -> list[str]:
    """Toate numerele de comandă din cont (sau primele `max_orders`)."""
    first = await _open_list_page(page, 1, progress)
    if not first:
        raise RuntimeError("nicio comandă pe prima pagină a listei (sesiune expirată sau pagină schimbată?)")
    all_ids = list(first)
    seen = set(first)
    last_hint = int(await page.evaluate(_LAST_PAGE_JS))
    logger.info("lista de comenzi: pagina 1 are %d comenzi, paginare până la %d", len(first), last_hint)

    page_no = 2
    while page_no <= settings.MAX_LIST_PAGES:
        if max_orders and len(all_ids) >= max_orders:
            break
        if page_no > last_hint > 1:
            break  # paginarea e cunoscută și am parcurs-o: nu mai cerem pagini goale
        progress.raise_if_cancelled()
        progress.message(f"Caut comenzile în cont: pagina {page_no}" + (f" din {last_hint}" if last_hint > 1 else ""))
        ids = await _open_list_page(page, page_no, progress)
        if not ids and page_no <= last_hint:
            ids = await _open_list_page(page, page_no, progress)  # a doua încercare, pagina poate fi lentă
        if not ids:
            if page_no > last_hint:
                break  # paginare necunoscută: am sondat o pagină în plus și e goală
            raise RuntimeError(f"pagina {page_no} din {last_hint} a listei nu s-a încărcat")
        new = [i for i in ids if i not in seen]
        if not new and page_no > last_hint:
            break
        for order_id in new:
            seen.add(order_id)
            all_ids.append(order_id)
        last_hint = max(last_hint, int(await page.evaluate(_LAST_PAGE_JS)))
        if page_no % 10 == 0:
            logger.info("lista de comenzi: pagina %d/%d, %d comenzi până acum", page_no, last_hint, len(all_ids))
        page_no += 1
    logger.info("lista de comenzi: %d comenzi unice pe %d pagini", len(all_ids), page_no - 1)
    return all_ids[:max_orders] if max_orders else all_ids

"""Colectează comenzile și retururile din contul eMAG (partea cu browser).

Primește: opțional o limită de comenzi (pentru teste rapide) și o funcție
apelată după fiecare etapă (ca datele să se salveze pe măsură ce vin).
Dă înapoi: (comenzi, retururi) deja parsate.
Orchestrează modulele browser_session, order_list_scraper, return_list_scraper
și page_fetcher; nu calculează nimic și nu scrie fișiere. Anunță fazele (comenzi, retururi) unui raportor de progres
(progress.py, implicit inactiv) și trece oprirea cerută de utilizator mai departe, către cei care o verifică.
"""

import logging
from typing import Callable

from emag_spend import settings
from emag_spend.browser_session import logged_in_browser
from emag_spend.html_lines import extract_product_names, html_to_lines
from emag_spend.models import Order, ReturnRequest
from emag_spend.order_list_scraper import collect_order_ids
from emag_spend.order_parser import parse_order
from emag_spend.page_fetcher import fetch_each
from emag_spend.progress import NO_PROGRESS, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, Progress
from emag_spend.return_list_scraper import collect_return_paths
from emag_spend.return_parser import parse_return

logger = logging.getLogger(__name__)


def _parse_order_page(path: str, html: str) -> Order:
    """Parsează pagina de detalii a unei comenzi (numărul comenzii e ultimul segment din cale)."""
    order_id = path.rsplit("/", 1)[-1]
    return parse_order(order_id, html_to_lines(html), extract_product_names(html))


def _parse_return_page(path: str, html: str) -> ReturnRequest:
    """Parsează pagina de detalii a unui retur."""
    return parse_return(path, html_to_lines(html))


async def collect_all(
    max_orders: int | None = None,
    on_orders: Callable[[list[Order]], None] | None = None,
    on_returns: Callable[[list[ReturnRequest]], None] | None = None,
    progress: Progress = NO_PROGRESS,
) -> tuple[list[Order], list[ReturnRequest]]:
    """Deschide browserul, așteaptă login-ul și citește toate comenzile și retururile."""
    async with logged_in_browser(progress) as (context, page):
        progress.phase(PHASE_FETCHING_ORDERS)
        order_ids = await collect_order_ids(page, max_orders, progress)
        paths = [settings.ORDER_DETAIL_PATH.format(order_id=order_id) for order_id in order_ids]
        progress.message("Citesc detaliile fiecărei comenzi.")
        orders = await fetch_each(context, paths, _parse_order_page, "comenzi", progress)
        if on_orders:
            on_orders(orders)

        progress.phase(PHASE_FETCHING_RETURNS)
        return_paths = await collect_return_paths(page, progress)
        progress.message("Citesc detaliile fiecărui retur.")
        returns = await fetch_each(context, return_paths, _parse_return_page, "retururi", progress)
        if on_returns:
            on_returns(returns)
    return orders, returns

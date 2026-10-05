"""Teste pentru parcurgerea listelor și descărcarea paginilor, cu obiecte simulate (fără browser).

Obiectele false imită doar ce folosește codul: `page.goto`, `page.evaluate`,
`page.locator(...)`, `context.request.get(...)`. Verifică logica noastră:
paginarea, duplicatele cauzate de o comandă nouă, retry-urile, sesiunea expirată.
"""

import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

from emag_spend import order_list_scraper, page_fetcher, return_list_scraper, settings


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    monkeypatch.setattr(settings, "LIST_RENDER_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(settings, "FETCH_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(order_list_scraper.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(return_list_scraper.asyncio, "sleep", _no_sleep)


async def _no_sleep(_seconds):
    return None


class FakeListPage:
    """Pagină de listă: fiecare `goto` schimbă pagina curentă; `evaluate` întoarce ce cere scriptul JS."""

    def __init__(self, pages: dict[int, list[str]], last_page: int):
        self.pages, self.last_page, self.current, self.visited = pages, last_page, 1, []

    async def goto(self, url, wait_until=None):
        marker = "/history/shopping/"
        self.current = int(url.split(marker)[1].split("?")[0]) if marker in url else 1
        self.visited.append(self.current)

    async def evaluate(self, script):
        if "shoppingdetails" in script:
            return list(self.pages.get(self.current, []))
        return self.last_page


def _run(coro):
    return asyncio.run(coro)


def test_collect_order_ids_walks_every_page_in_order():
    page = FakeListPage({1: ["10", "9"], 2: ["8", "7"], 3: ["6"]}, last_page=3)
    assert _run(order_list_scraper.collect_order_ids(page)) == ["10", "9", "8", "7", "6"]
    assert page.visited == [1, 2, 3]


def test_collect_order_ids_removes_duplicates_when_pages_shift():
    # o comandă nouă a apărut între cereri: "8" ajunge și la sfârșitul paginii 1 și la începutul paginii 2
    page = FakeListPage({1: ["10", "9", "8"], 2: ["8", "7", "6"]}, last_page=2)
    assert _run(order_list_scraper.collect_order_ids(page)) == ["10", "9", "8", "7", "6"]


def test_collect_order_ids_ignores_placeholder_skeletons():
    page = FakeListPage({1: ["000000000", "000000000", "000000000"]}, last_page=1)
    with pytest.raises(RuntimeError, match="nicio comandă"):
        _run(order_list_scraper.collect_order_ids(page))


def test_collect_order_ids_stops_past_the_last_page_when_pagination_is_unknown():
    page = FakeListPage({1: ["3", "2"], 2: ["1"]}, last_page=1)  # paginare necunoscută (1), dar există pagina 2
    assert _run(order_list_scraper.collect_order_ids(page)) == ["3", "2", "1"]
    assert page.visited == [1, 2, 3]  # a sondat pagina 3, goală, o singură dată, și s-a oprit


def test_collect_order_ids_fails_loudly_when_a_middle_page_stays_empty():
    page = FakeListPage({1: ["5", "4"], 3: ["1"]}, last_page=3)
    with pytest.raises(RuntimeError, match="pagina 2"):
        _run(order_list_scraper.collect_order_ids(page))


def test_collect_order_ids_respects_the_limit():
    page = FakeListPage({1: ["10", "9"], 2: ["8", "7"], 3: ["6"]}, last_page=3)
    assert _run(order_list_scraper.collect_order_ids(page, max_orders=3)) == ["10", "9", "8"]


class FakeResponse:
    def __init__(self, status=200, text="<html></html>", url="https://www.emag.ro/x"):
        self.status, self._text, self.url = status, text, url

    async def text(self):
        return self._text


class FakeContext:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.request = self

    async def get(self, url, timeout=None):
        self.calls.append(url)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def test_fetch_each_keeps_path_order_and_applies_handler():
    context = FakeContext([FakeResponse(text="A")])
    out = _run(page_fetcher.fetch_each(context, ["/p/1", "/p/2", "/p/3"], lambda path, html: path + ":" + html, "test"))
    assert out == ["/p/1:A", "/p/2:A", "/p/3:A"]


def test_fetch_retries_after_a_transient_error():
    context = FakeContext([RuntimeError("timeout"), FakeResponse(text="ok")])
    out = _run(page_fetcher.fetch_each(context, ["/p/1"], lambda p, h: h, "test"))
    assert out == ["ok"] and len(context.calls) == 2


def test_fetch_gives_up_after_the_configured_retries():
    context = FakeContext([FakeResponse(status=500)])
    with pytest.raises(RuntimeError, match="nu am putut descărca"):
        _run(page_fetcher.fetch_each(context, ["/p/1"], lambda p, h: h, "test"))
    assert len(context.calls) == settings.FETCH_RETRIES


def test_fetch_detects_expired_session_by_login_redirect():
    context = FakeContext([FakeResponse(url="https://auth.emag.ro/user/login")])
    with pytest.raises(page_fetcher.SessionExpired):
        _run(page_fetcher.fetch_each(context, ["/p/1"], lambda p, h: h, "test"))
    assert len(context.calls) == 1  # fără reîncercări inutile


class FakeReturnPage:
    """Pagina de retururi: fiecare apăsare pe 'Vezi mai mult' dezvăluie încă un lot."""

    def __init__(self, batches):
        self.batches, self.shown = batches, 1
        self.clicks = 0

    async def goto(self, url, wait_until=None):
        return None

    async def wait_for_selector(self, selector, timeout=None):
        return None

    async def evaluate(self, script):
        return [p for batch in self.batches[: self.shown] for p in batch]

    def locator(self, selector):
        page = self

        class Button:
            @property
            def first(self):
                return self

            async def count(self):
                return 1 if page.shown < len(page.batches) else 0

            async def is_visible(self):
                return page.shown < len(page.batches)

            async def click(self):
                page.clicks += 1
                page.shown += 1

        return Button()


def test_collect_return_paths_clicks_until_all_batches_are_shown():
    batches = [[f"/user/return-history/1/{i}" for i in range(10)], ["/user/return-history/1/10", "/user/return-history/1/11"]]
    page = FakeReturnPage(batches)
    paths = _run(return_list_scraper.collect_return_paths(page))
    assert len(paths) == 12 and page.clicks == 1


class FakeEmptyReturnPage:
    """Cont fără retururi: pagina se încarcă, dar nu apare nicio legătură, deci așteptarea expiră."""

    def __init__(self, url="https://www.emag.ro/user/return-history"):
        self.url = url

    async def goto(self, url, wait_until=None):
        return None

    async def wait_for_selector(self, selector, timeout=None):
        raise PlaywrightTimeout(f"Page.wait_for_selector: Timeout {timeout}ms exceeded.")


def test_account_without_returns_gives_an_empty_list_and_a_log_warning(caplog):
    # înainte, TimeoutError ieșea necaptat din colectare și rularea cădea după ce citise deja toate comenzile
    caplog.set_level("WARNING", logger=return_list_scraper.logger.name)
    assert _run(return_list_scraper.collect_return_paths(FakeEmptyReturnPage())) == []
    assert any("niciun retur" in record.getMessage() for record in caplog.records)


def test_login_redirect_on_the_return_list_is_an_expired_session_not_an_empty_list():
    # fără distincția asta, o sesiune expirată ar da „zero retururi” și raportul ar număra produsele returnate ca păstrate
    page = FakeEmptyReturnPage(url="https://auth.emag.ro/user/login?redirect=return-history")
    with pytest.raises(page_fetcher.SessionExpired, match="login"):
        _run(return_list_scraper.collect_return_paths(page))

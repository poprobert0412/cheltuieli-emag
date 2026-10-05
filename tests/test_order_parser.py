"""Teste pentru parserul paginii de detalii comandă (pagini inventate)."""

import json

import pytest

from emag_spend import block_status, warning_messages
from emag_spend.html_lines import extract_product_names, html_to_lines
from emag_spend.models import to_dict
from emag_spend.order_parser import parse_order
from tests.html_builders import FAKE_ADDRESS, FAKE_NAME, FAKE_PHONE, order_page


def _parse(order_id, html):
    """Calea folosită de aplicație: linii + nume de produse citite structural din HTML."""
    return parse_order(order_id, html_to_lines(html), extract_product_names(html))


def _parse_lines_only(order_id, html):
    """Doar liniile de text (plasa de siguranță când structura HTML nu se recunoaște)."""
    return parse_order(order_id, html_to_lines(html))


def _simple_block(**overrides):
    block = dict(
        header="Produse vandute si livrate de eMAG",
        seller_label="eMAG",
        status=["Produse ridicate"],
        items=[("Rucsac Alfa Test, Negru", "105,99", 1), ("Rucsac Beta Test, Alb", "116,99", 1)],
        total_products="222,98",
        vouchers=["-34,00"],
        shipping="GRATUIT",
        services=["1,49"],
        paid="190,47",
    )
    block.update(overrides)
    return block


@pytest.mark.parametrize("layout", ["inline", "stacked"])
def test_single_delivered_block_with_voucher_and_service(layout):
    order = _parse("489000001", order_page("489000001", "26 mai 2026, 10:07", "190,47", [_simple_block()], layout))
    assert order.order_id == "489000001"
    assert order.placed_at == "2026-05-26T10:07"
    assert order.year == 2026
    assert order.header_total_bani == 19047
    assert order.warnings == []
    (block,) = order.blocks
    assert block.seller == "eMAG"
    assert block.status == block_status.DELIVERED
    assert [(i.name, i.line_total_bani, i.qty) for i in block.items] == [
        ("Rucsac Alfa Test, Negru", 10599, 1), ("Rucsac Beta Test, Alb", 11699, 1),
    ]
    assert block.products_total_bani == 22298
    assert block.vouchers_bani == [-3400]
    assert block.shipping_bani == 0
    assert block.services_bani == [149]
    assert block.paid_bani == 19047
    assert block.has_storno is False


@pytest.mark.parametrize("layout", ["inline", "stacked"])
def test_multi_seller_with_cancelled_marketplace_block(layout):
    delivered = _simple_block(
        items=[("Pantofi Test, Negru, 42", "167,99", 1)], total_products="167,99",
        vouchers=["-25,00"], services=["1,99"], paid="144,98",
    )
    cancelled = dict(
        header="Produse vandute de ALFA SRL si livrate de eMAG", seller_label="ALFA SRL",
        status=["Am trimis cererea de anulare catre ALFA SRL. Statusul comenzii va fi actualizat.", "Livrare anulata"],
        items=[("Pantofi Test Marketplace, Gri, 43", "239,99", 1)], total_products="239,99",
        shipping="GRATUIT", paid="239,99",
    )
    order = _parse("489000002", order_page("489000002", "15 iunie 2026, 12:55", "384,97", [delivered, cancelled], layout))
    assert order.warnings == []
    assert [b.status for b in order.blocks] == [block_status.DELIVERED, block_status.CANCELLED]
    assert order.blocks[1].seller == "ALFA SRL"
    assert order.blocks[1].paid_bani == 23999
    assert sum(b.paid_bani for b in order.blocks) == order.header_total_bani


def test_marketplace_header_variant_and_insurance_block():
    block = _simple_block(
        header="Produse vandute si livrate de eMAG Asigurari", seller_label="eMAG Asigurari",
        status=["Plata acceptata"], items=[("Asigurare Test", "2.335,78", 1)],
        total_products="2.335,78", vouchers=[], services=[], paid="2.335,78",
    )
    order = _parse("489000003", order_page("489000003", "3 sep 2026, 18:53", "2.335,78", [block]))
    assert order.blocks[0].seller == "eMAG Asigurari"
    assert order.blocks[0].status == block_status.PAID_ONLY
    assert order.blocks[0].items[0].line_total_bani == 233578
    assert order.warnings == []


def test_quantity_with_unit_price_is_converted_to_line_total():
    block = _simple_block(items=[("Cablu Test", "10,00", 3)], total_products="30,00", vouchers=[], services=[], paid="30,00")
    order = _parse("489000004", order_page("489000004", "1 oct 2026, 22:27", "30,00", [block]))
    item = order.blocks[0].items[0]
    assert (item.line_total_bani, item.qty) == (3000, 3)
    assert order.warnings == []


def test_quantity_with_line_total_is_kept_as_is():
    block = _simple_block(items=[("Cablu Test", "20,00", 2)], total_products="20,00", vouchers=[], services=[], paid="20,00")
    order = _parse("489000005", order_page("489000005", "1 oct 2026, 22:27", "20,00", [block]))
    item = order.blocks[0].items[0]
    assert (item.line_total_bani, item.qty) == (2000, 2)
    assert order.warnings == []


def test_sum_of_items_not_matching_total_produse_warns():
    block = _simple_block(items=[("Produs Test", "10,00", 1)], total_products="12,00", vouchers=[], services=[], paid="12,00")
    order = _parse("489000006", order_page("489000006", "1 oct 2026, 22:27", "12,00", [block]))
    assert any("suma produselor" in w for w in order.warnings)


def test_paid_not_matching_components_warns():
    block = _simple_block(paid="190,00")
    order = _parse("489000007", order_page("489000007", "1 oct 2026, 22:27", "190,00", [block]))
    assert any("total plătit" in w for w in order.warnings)


def test_unknown_fee_line_is_collected_and_balances_the_total():
    block = _simple_block(
        items=[("Produs Test", "100,00", 1)], total_products="100,00", vouchers=[], services=[],
        other=[("Taxa de ambalare:", "2,50")], paid="102,50",
    )
    order = _parse("489000008", order_page("489000008", "1 oct 2026, 22:27", "102,50", [block]))
    assert order.blocks[0].other_bani == [250]
    assert order.warnings == []


def test_storno_invoice_is_detected():
    order = _parse("489000009", order_page("489000009", "26 mai 2026, 10:07", "190,47", [_simple_block(storno=True)]))
    assert order.blocks[0].has_storno is True


def test_cancelled_order_without_header_total():
    block = _simple_block(status=["Livrare anulata"], vouchers=[], services=[], items=[("Produs Test", "84,99", 1)],
                          total_products="84,99", paid="84,99")
    order = _parse("489000010", order_page("489000010", "9 feb 2025, 19:54", None, [block]))
    assert order.header_total_bani is None
    assert order.blocks[0].status == block_status.CANCELLED


def test_personal_data_is_never_stored():
    order = _parse("489000011", order_page("489000011", "26 mai 2026, 10:07", "190,47", [_simple_block()]))
    dumped = json.dumps(to_dict(order), ensure_ascii=False)
    for secret in (FAKE_NAME, FAKE_PHONE, FAKE_ADDRESS, "easybox"):
        assert secret not in dumped


def test_attribute_line_under_the_product_name_is_not_taken_as_the_name():
    block = _simple_block(
        items=[("Controller Test Wireless", "349,99", 1, "garantie electronica"), ("Cablu Test", "10,00", 1, "ghidul utilizatorului")],
        total_products="359,99", vouchers=[], services=[], paid="359,99",
    )
    html = order_page("489000020", "26 mai 2026, 10:07", "359,99", [block])
    for order in (_parse("489000020", html), _parse_lines_only("489000020", html)):
        assert [i.name for i in order.blocks[0].items] == ["Controller Test Wireless", "Cablu Test"]
        assert order.warnings == []


def test_bundle_row_gets_one_name_made_of_its_components():
    block = _simple_block(
        items=[("Pachet", "25,50", 1, None, ["Deodorant Test A, 150 ml", "Deodorant Test B, 150 ml"]), ("Cablu Test", "10,00", 1)],
        total_products="35,50", vouchers=[], services=[], paid="35,50",
    )
    order = _parse("489000023", order_page("489000023", "26 mai 2026, 10:07", "35,50", [block]))
    assert [i.name for i in order.blocks[0].items] == ["Pachet: Deodorant Test A, 150 ml + Deodorant Test B, 150 ml", "Cablu Test"]
    assert [i.line_total_bani for i in order.blocks[0].items] == [2550, 1000]
    assert order.warnings == []


def test_name_count_mismatch_falls_back_to_line_names_with_a_warning():
    html = order_page("489000021", "26 mai 2026, 10:07", "190,47", [_simple_block()])
    order = parse_order("489000021", html_to_lines(html), ["un singur nume"])
    assert [i.name for i in order.blocks[0].items] == ["Rucsac Alfa Test, Negru", "Rucsac Beta Test, Alb"]
    assert any("nume de produs în HTML" in w for w in order.warnings)


def test_cancelled_block_with_zero_total_paid_does_not_warn():
    block = _simple_block(status=["Livrare anulata"], vouchers=[], services=[], items=[("Produs Test", "84,99", 1)],
                          total_products="84,99", paid="0,00")
    order = _parse("489000022", order_page("489000022", "9 feb 2025, 19:54", None, [block]))
    assert order.warnings == []
    assert order.blocks[0].paid_bani == 0


def test_labels_with_amount_glued_without_colon():
    lines = [
        "Comanda nr. 777", "Plasata pe: 1 oct 2026, 22:27 Total: 30,00 Lei",
        "Produse vandute si livrate de eMAG", "Produse ridicate", "Istoric livrare",
        "Produs Test", "30,00 Lei", "1 buc",
        "Total produse 30,00 Lei", "Cost livrare GRATUIT", "Total platit eMAG 30,00 Lei",
    ]
    order = parse_order("777", lines)
    block = order.blocks[0]
    assert (block.products_total_bani, block.shipping_bani, block.paid_bani) == (3000, 0, 3000)
    assert order.warnings == []


def test_label_with_own_text_and_no_amount_does_not_steal_the_next_line():
    lines = [
        "Comanda nr. 778", "Produse vandute si livrate de eMAG", "Produse ridicate", "Istoric livrare",
        "Produs Test", "30,00 Lei", "1 buc", "Total produse:", "30,00 Lei",
        "Cost livrare: la ridicare", "99,99 Lei", "Total platit eMAG:", "30,00 Lei",
    ]
    block = parse_order("778", lines).blocks[0]
    assert block.shipping_bani is None
    assert block.paid_bani == 3000


def test_page_without_order_header_raises():
    with pytest.raises(ValueError, match="sesiune expirată"):
        parse_order("1", ["Autentificare", "Parola"])


def test_order_number_mismatch_warns():
    order = _parse("999", order_page("489000012", "26 mai 2026, 10:07", "190,47", [_simple_block()]))
    assert any("≠ numărul cerut" in w for w in order.warnings)


def test_order_without_any_seller_block_warns():
    order = _parse("489000013", order_page("489000013", "26 mai 2026, 10:07", None, []))
    assert order.blocks == []
    assert any("nicio secțiune" in w for w in order.warnings)


def test_script_text_in_page_does_not_create_totals():
    # builder-ul pune un <script> cu "Total produse: 1,00 Lei"; nu trebuie citit
    order = _parse("489000014", order_page("489000014", "26 mai 2026, 10:07", "190,47", [_simple_block()]))
    assert order.blocks[0].products_total_bani == 22298


def _block_without_total_platit(status_lines, seller="ALFA SRL", **overrides):
    """Un bloc la care pagina arată „Total de plata” (de plătit) în loc de „Total platit”."""
    block = dict(
        header=f"Produse vandute de {seller} si livrate de eMAG", seller_label=seller, status=status_lines,
        items=[("Produs Test Fara Total", "84,99", 1)], total_products="84,99", shipping="GRATUIT", to_pay="84,99",
    )
    block.update(overrides)
    return block


@pytest.mark.parametrize("layout", ["inline", "stacked"])
def test_cancelled_block_without_total_platit_does_not_warn(layout):
    # bloc anulat: pagina eMAG arată „Total de plata”, nu „Total platit”; lipsa lui nu e o problemă de citit
    block = _block_without_total_platit(["Am trimis cererea de anulare catre ALFA SRL.", "Livrare anulata"])
    order = _parse("489000030", order_page("489000030", "9 feb 2025, 19:54", None, [block], layout))
    assert order.warnings == []
    assert order.blocks[0].status == block_status.CANCELLED and order.blocks[0].paid_bani is None


@pytest.mark.parametrize("status_line, expected_status", [
    ("Produse livrate", block_status.DELIVERED),
    ("Comanda plasata", block_status.IN_PROGRESS),
    ("Plata acceptata", block_status.PAID_ONLY),
    ("Un status pe care programul nu-l cunoaste", block_status.UNKNOWN),
])
def test_any_other_block_without_total_platit_still_warns_with_the_shared_message(status_line, expected_status):
    block = _block_without_total_platit([status_line])
    order = _parse("489000031", order_page("489000031", "9 feb 2025, 19:54", "84,99", [block]))
    assert order.blocks[0].status == expected_status
    assert order.warnings == [warning_messages.format_missing_paid_total("489000031", "ALFA SRL")]
    parsed = warning_messages.parse_order_warning(order.warnings[0])
    assert (parsed.kind, parsed.order_ids, parsed.seller) == (
        warning_messages.KIND_MISSING_PAID_TOTAL, ("489000031",), "ALFA SRL")


def test_order_with_one_delivered_and_one_cancelled_block_is_clean_when_only_the_cancelled_one_lacks_the_total():
    delivered = _simple_block()
    cancelled = _block_without_total_platit(["Livrare anulata"])
    order = _parse("489000032", order_page("489000032", "15 iunie 2026, 12:55", "190,47", [delivered, cancelled]))
    assert order.warnings == []


def test_amount_warnings_show_lei_not_raw_bani():
    block = _simple_block(items=[("Produs Test", "10,00", 1)], total_products="12,00", vouchers=[], services=[], paid="12,00")
    order = _parse("489000033", order_page("489000033", "1 oct 2026, 22:27", "12,00", [block]))
    assert order.warnings == [warning_messages.format_products_sum_mismatch("489000033", "eMAG", 1000, 1200)]
    assert "10,00 Lei" in order.warnings[0] and "12,00 Lei" in order.warnings[0]

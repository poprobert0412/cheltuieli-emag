"""Teste pentru mesajele de avertisment (warning_messages.py) și grupele lor (warning_details.py).

Toate numele, numerele și sumele sunt inventate. Se verifică: citirea înapoi a fiecărui mesaj,
gruparea corectă, ordinea, `count == len(items)`, textele din config/avertismente.json și
respingerea unui config greșit cu mesaj care numește fișierul și grupa.
"""

import copy
import json
import logging

import pytest

from emag_spend import block_status, warning_messages as wm
from emag_spend.models import Item, Order, ReturnRequest, SellerBlock
from emag_spend.spend_analysis import analyze
from emag_spend.warning_details import (
    MAX_PRODUCT_NAMES_IN_TEXT, WARNING_TEXTS_FILE, build_warnings_detail, current_order_warnings, load_warning_texts,
)
from tests import scenario

TEXTS = load_warning_texts()
SELLER_WITH_PUNCTUATION = "Firma: Test, Alfa SRL"  # două puncte și virgulă în nume: citirea nu are voie să se încurce

# (text produs de format_*, tip, comenzi, vânzător, retur, număr, poate afecta totalurile)
ROUND_TRIP_CASES = [
    (wm.format_missing_paid_total("100100", "Firma SRL"), wm.KIND_MISSING_PAID_TOTAL, ("100100",), "Firma SRL", None, None, False),
    (wm.format_missing_paid_total("100100", SELLER_WITH_PUNCTUATION), wm.KIND_MISSING_PAID_TOTAL, ("100100",),
     SELLER_WITH_PUNCTUATION, None, None, False),
    (wm.format_missing_products_total("100101", "Firma SRL"), wm.KIND_OTHER, ("100101",), "Firma SRL", None, None, False),
    (wm.format_products_sum_mismatch("100102", "Firma SRL", 1000, 1200), wm.KIND_OTHER, ("100102",), "Firma SRL", None, None, True),
    (wm.format_paid_mismatch("100103", "Firma SRL", 1000, 1200), wm.KIND_OTHER, ("100103",), "Firma SRL", None, None, False),
    (wm.format_no_products("100104", "Firma SRL"), wm.KIND_OTHER, ("100104",), "Firma SRL", None, None, True),
    (wm.format_order_number_mismatch("100105", "100106"), wm.KIND_OTHER, ("100105",), None, None, None, True),
    (wm.format_name_count_mismatch("100107", 2, 3), wm.KIND_OTHER, ("100107",), None, None, None, False),
    (wm.format_no_seller_section("100108"), wm.KIND_OTHER, ("100108",), None, None, None, True),
    (wm.format_unknown_status("100109", "Firma SRL", "un status nou"), wm.KIND_OTHER, ("100109",), "Firma SRL", None, None, True),
    (wm.format_unknown_status("100109", SELLER_WITH_PUNCTUATION, "stare: ciudată"), wm.KIND_OTHER, ("100109",),
     SELLER_WITH_PUNCTUATION, None, None, True),
    (wm.format_pending_returns(1), wm.KIND_PENDING_RETURN, (), None, None, 1, False),
    (wm.format_pending_returns(7), wm.KIND_PENDING_RETURN, (), None, None, 7, False),
    (wm.format_refunds_without_amount(1), wm.KIND_COMPLETED_RETURN_NO_REFUND, (), None, None, 1, False),
    (wm.format_refunds_without_amount(12), wm.KIND_COMPLETED_RETURN_NO_REFUND, (), None, None, 12, False),
    (wm.format_header_mismatches(1), wm.KIND_HEADER_MISMATCH, (), None, None, 1, False),
    (wm.format_header_mismatches(25), wm.KIND_HEADER_MISMATCH, (), None, None, 25, False),
    (wm.format_highlight_category_missing("Categorie Inventata"), wm.KIND_OTHER, (), None, None, None, False),
    (wm.format_funnel_not_closing(10000, 9900), wm.KIND_OTHER, (), None, None, None, True),
    (wm.format_paid_not_closing(wm.PAID_CHECK_CHAIN, 10000, 9900), wm.KIND_OTHER, (), None, None, None, True),
    (wm.format_paid_not_closing(wm.PAID_CHECK_BLOCKS, 10000, 10100), wm.KIND_OTHER, (), None, None, None, True),
    (wm.format_uncategorized(4), wm.KIND_OTHER, (), None, None, None, False),
    ("retur 3001: nu are produse listate", wm.KIND_OTHER, (), None, "3001", None, True),
]


@pytest.mark.parametrize("text, kind, order_ids, seller, return_id, count, affects", ROUND_TRIP_CASES)
def test_every_message_is_read_back_into_the_same_facts(text, kind, order_ids, seller, return_id, count, affects):
    parsed = wm.parse_order_warning(text)
    assert (parsed.kind, parsed.order_ids, parsed.seller, parsed.return_id, parsed.count, parsed.affects_totals) == (
        kind, order_ids, seller, return_id, count, affects)
    assert parsed.text == text


def test_singular_and_plural_forms_are_both_grammatical_and_distinct():
    assert wm.format_pending_returns(1).startswith("1 retur cu") and wm.format_pending_returns(2).startswith("2 retururi cu")
    assert wm.format_refunds_without_amount(1).startswith("1 retur finalizat ")
    assert wm.format_header_mismatches(1).startswith("1 comandă la care")
    assert wm.format_header_mismatches(2).startswith("2 comenzi la care")


def test_original_wordings_that_other_files_and_tests_look_for_are_kept():
    assert "fără rezultat" in wm.format_pending_returns(3)
    assert "necategorizate" in wm.format_uncategorized(2)
    assert "evidențiată" in wm.format_highlight_category_missing("X") and "«X»" in wm.format_highlight_category_missing("X")
    assert "status necunoscut" in wm.format_unknown_status("100", "F", "x")
    assert "lipsește 'Total platit'" in wm.format_missing_paid_total("100", "F")


def test_the_uncategorized_warning_sends_the_user_to_the_personal_rules_that_updates_keep():
    """N15 (decis 6 oct. 2026): regulile noi merg în config/categorii.personal.json (păstrat la actualizare), nu în categorii.json
    (fișier al programului, înlocuit); la fel și textul „Ce faci” al grupei din config/avertismente.json."""
    from emag_spend import settings
    personal = f"config/{settings.PERSONAL_CATEGORY_RULES_FILE_NAME}"
    public = f"config/{settings.CATEGORY_RULES_FILE.name}"
    assert settings.CATEGORY_RULES_FILE.parent.name == "config"
    assert wm.format_uncategorized(2) == f"2 produse necategorizate (adaugă reguli în {personal})"
    other = TEXTS["grupe"][wm.KIND_OTHER]["what_to_do"]
    assert personal in other and f"în {public}" not in other, other


@pytest.mark.parametrize("text", [
    "", " ", "ceva ce nu seamănă cu niciun mesaj", "comanda: fără număr", "comanda 12a, Firma: x", "retur 12a: x",
    "comanda ١٢٣٤: x", "1 retururi cu cerere înregistrată dar fără rezultat", "x" * 10_000, "\n\n", "comanda 100 fără virgulă și fără două puncte",
])
def test_unknown_or_odd_text_never_raises_and_keeps_the_whole_text(text):
    parsed = wm.parse_order_warning(text)
    assert parsed.kind == wm.KIND_OTHER and parsed.text == text and parsed.order_ids == ()


def test_message_templates_and_reader_cannot_drift_apart():
    # citirea se construiește din aceleași șabloane: orice număr de comandă generat o satisface
    for order_id in ("100", "100100100100100"):
        for seller in ("eMAG", "Firma & Fiii SRL", "a: b: c", "x, y", "„Ghilimele” 'simple'"):
            parsed = wm.parse_order_warning(wm.format_missing_paid_total(order_id, seller))
            assert parsed.kind == wm.KIND_MISSING_PAID_TOTAL and parsed.order_ids == (order_id,) and parsed.seller == seller


# --- date inventate pentru grupare -------------------------------------------------------------

def _block(seller="Vanzator Alfa SRL", status=block_status.DELIVERED, paid=1000, name="Produs Test"):
    return SellerBlock(seller, status, "x", False, [Item(name, 1000, 1)], 1000, [], 0, [], [], paid)


def _order(order_id, placed_at, *blocks, header=None):
    return Order(order_id, placed_at or "", placed_at, header, list(blocks) or [_block()])


def _ret(return_id, order_ids, names=("Produs Test",), steps=("Cerere inregistrata",), refund=None, completed=False,
         cancelled=False, mode="Vreau banii inapoi", path=None):
    return ReturnRequest(return_id, path or f"/user/return-history/1/{return_id}", list(order_ids), list(names),
                         list(steps), refund, mode, completed, cancelled)


def _fixture():
    orders = [
        _order("100100100", "2026-03-02T10:00", _block(paid=None), header=0),
        _order("100100050", "2025-12-01T09:00", _block("Firma Beta SRL", block_status.IN_PROGRESS, paid=None), header=0),
        _order("100100200", "2026-04-01T12:00", _block(paid=12000), header=12550),
        _order("100100300", None, _block(paid=500), header=900),
    ]
    returns = [
        _ret("3000001", ["100100200"], names=[f"Produs {i}" for i in range(1, 6)],
             steps=["Cerere inregistrata", "Receptionare produs"]),
        _ret("3000002", ["100100100"], steps=["Cerere inregistrata", "Restituire suma"], completed=True, mode="Emitere voucher"),
        _ret("3000003", ["100100200"], steps=["Restituire suma"], completed=True, refund=5000),  # cu sumă: nu e avertisment
        _ret("3000004", ["100100200"], steps=["Cerere anulata"], cancelled=True),  # anulat: nu e avertisment
    ]
    header_mismatches = [
        {"order_id": "100100300", "header_bani": 900, "blocks_bani": 500},
        {"order_id": "100100200", "header_bani": 12550, "blocks_bani": 12000},
    ]
    warnings = [
        wm.format_missing_paid_total("100100100", "Vanzator Alfa SRL"),
        wm.format_missing_paid_total("100100050", "Firma Beta SRL"),
        wm.format_pending_returns(1),
        wm.format_refunds_without_amount(1),
        wm.format_header_mismatches(2),
        wm.format_products_sum_mismatch("100100100", "Vanzator Alfa SRL", 1000, 1200),
        wm.format_uncategorized(2),
        "retur 3000002: nu are produse listate",
    ]
    return warnings, orders, returns, header_mismatches


def _groups(warnings=None, orders=None, returns=None, header_mismatches=None):
    base = _fixture()
    args = [a if a is not None else b for a, b in zip((warnings, orders, returns, header_mismatches), base)]
    return build_warnings_detail(*args, TEXTS)


def _by_kind(groups):
    return {g["kind"]: g for g in groups}


def test_groups_come_in_the_fixed_order_and_each_count_equals_its_items():
    groups = _groups()
    assert [g["kind"] for g in groups] == list(wm.ALL_KINDS)
    for group in groups:
        assert group["count"] == len(group["items"]) >= 1


def test_only_non_empty_groups_are_returned():
    assert _groups([], [], [], []) == []
    only_header = _groups([wm.format_header_mismatches(1)], returns=[], header_mismatches=[
        {"order_id": "100100200", "header_bani": 12550, "blocks_bani": 12000}])
    assert [g["kind"] for g in only_header] == [wm.KIND_HEADER_MISMATCH]


def test_group_texts_come_from_the_config_file():
    for group in _groups():
        config = TEXTS["grupe"][group["kind"]]
        assert (group["title"], group["explanation"], group["what_to_do"]) == (
            config["title"], config["explanation"], config["what_to_do"])


def test_header_mismatch_lists_each_order_with_both_sums_chronologically_undated_last():
    group = _by_kind(_groups())[wm.KIND_HEADER_MISMATCH]
    assert [i["order_ids"] for i in group["items"]] == [["100100200"], ["100100300"]]
    assert "total din antet 125,50 Lei, suma blocurilor 120,00 Lei" in group["items"][0]["text"]
    assert "total din antet 9,00 Lei, suma blocurilor 5,00 Lei" in group["items"][1]["text"]
    assert [i["placed_at"] for i in group["items"]] == ["2026-04-01", None]
    assert group["affects_totals"] is False


def test_missing_paid_total_items_are_sorted_by_date_and_name_the_seller_and_status():
    group = _by_kind(_groups())[wm.KIND_MISSING_PAID_TOTAL]
    assert [i["order_ids"] for i in group["items"]] == [["100100050"], ["100100100"]]  # 2025-12 înaintea lui 2026-03
    first = group["items"][0]
    assert first["seller"] == "Firma Beta SRL" and first["placed_at"] == "2025-12-01"
    assert first["status"] == TEXTS["etichete_status"][block_status.IN_PROGRESS]
    assert "Firma Beta SRL" in first["text"] and first["return_id"] is None and first["return_url"] is None


def test_pending_return_item_has_the_return_orders_last_step_and_a_real_address():
    group = _by_kind(_groups())[wm.KIND_PENDING_RETURN]
    (item,) = group["items"]
    assert (item["return_id"], item["order_ids"], item["status"], item["placed_at"]) == (
        "3000001", ["100100200"], "Receptionare produs", "2026-04-01")
    assert item["return_url"] == "https://www.emag.ro/user/return-history/1/3000001"
    assert "Produs 1; Produs 2; Produs 3" in item["text"] and "Produs 4" not in item["text"]
    assert f"încă {5 - MAX_PRODUCT_NAMES_IN_TEXT}" in item["text"] and "Receptionare produs" in item["text"]
    assert group["affects_totals"] is True


def test_completed_return_without_refund_ignores_returns_with_a_refund_and_cancelled_ones():
    group = _by_kind(_groups())[wm.KIND_COMPLETED_RETURN_NO_REFUND]
    assert [i["return_id"] for i in group["items"]] == ["3000002"]
    assert "Emitere voucher" in group["items"][0]["text"] and group["items"][0]["placed_at"] == "2026-03-02"


def test_return_address_is_none_when_the_saved_path_is_not_valid():
    returns = [_ret("3000001", ["100100200"], path="/oriunde/3000001")]
    (item,) = _by_kind(_groups(returns=returns))[wm.KIND_PENDING_RETURN]["items"]
    assert item["return_url"] is None


def test_other_group_keeps_the_full_message_and_links_orders_and_returns():
    group = _by_kind(_groups())[wm.KIND_OTHER]
    by_text = {i["text"]: i for i in group["items"]}
    sum_item = by_text[wm.format_products_sum_mismatch("100100100", "Vanzator Alfa SRL", 1000, 1200)]
    assert sum_item["order_ids"] == ["100100100"] and sum_item["seller"] == "Vanzator Alfa SRL"
    assert sum_item["placed_at"] == "2026-03-02"
    plain = by_text[wm.format_uncategorized(2)]
    assert plain["order_ids"] == [] and plain["placed_at"] is None
    returned = by_text["retur 3000002: nu are produse listate"]
    assert returned["return_id"] == "3000002" and returned["return_url"].endswith("/user/return-history/1/3000002")


def test_other_group_is_marked_as_affecting_totals_only_when_a_message_says_so():
    quiet = _groups([wm.format_uncategorized(2), wm.format_paid_mismatch("100100100", "Vanzator Alfa SRL", 1, 2)])
    assert _by_kind(quiet)[wm.KIND_OTHER]["affects_totals"] is False
    loud = _groups([wm.format_uncategorized(2), wm.format_unknown_status("100100100", "Vanzator Alfa SRL", "x")])
    assert _by_kind(loud)[wm.KIND_OTHER]["affects_totals"] is True


def test_each_item_has_exactly_the_schema_keys_and_the_result_is_json():
    for group in _groups():
        assert list(group) == ["kind", "title", "explanation", "affects_totals", "what_to_do", "count", "items"]
        for item in group["items"]:
            assert set(item) == {"order_ids", "return_id", "seller", "status", "placed_at", "text", "return_url"}
            assert isinstance(item["order_ids"], list) and isinstance(item["text"], str)
    assert json.loads(json.dumps(_groups())) == _groups()


def test_a_count_in_a_message_that_disagrees_with_the_data_is_logged_and_the_data_wins(caplog):
    with caplog.at_level(logging.WARNING, logger="emag_spend.warning_details"):
        groups = _groups([wm.format_pending_returns(5)])
    assert _by_kind(groups)[wm.KIND_PENDING_RETURN]["count"] == 1
    assert "spune 5" in caplog.text


def test_the_flat_warnings_list_is_left_untouched():
    warnings, orders, returns, mismatches = _fixture()
    before = list(warnings)
    build_warnings_detail(warnings, orders, returns, mismatches, TEXTS)
    assert warnings == before


# --- cap la cap, prin analyze() -----------------------------------------------------------------

def _analysis_with_defects():
    orders = scenario.orders()
    missing = _order("100200300", "2026-05-01T10:00", _block(paid=None), header=0)  # livrat, fără „Total platit”
    missing.warnings = [wm.format_missing_paid_total("100200300", "Vanzator Alfa SRL")]
    orders.append(missing)
    orders[6].header_total_bani += 777  # comanda G: antetul ≠ suma blocurilor
    returns = scenario.returns()
    returns.append(_ret("R4", ["G"], names=["Laptop Test"], steps=["Cerere inregistrata"]))
    returns.append(_ret("R5", ["A"], names=["Televizor Alfa 55 inch"], steps=["Restituire suma"], completed=True))
    return analyze(orders, returns, scenario.classifier(), 50000, "2026-10-04 12:00").summary


def test_analysis_counts_in_the_flat_messages_match_the_lists_in_the_groups():
    summary = _analysis_with_defects()
    groups = _by_kind(summary["warnings_detail"])
    rec = summary["reconciliation"]
    assert groups[wm.KIND_HEADER_MISMATCH]["count"] == len(rec["header_total_mismatches"]) == 1
    assert [i["order_ids"] for i in groups[wm.KIND_HEADER_MISMATCH]["items"]] == [["G"]]
    assert groups[wm.KIND_PENDING_RETURN]["count"] == rec["returns_pending"] == 1
    assert groups[wm.KIND_COMPLETED_RETURN_NO_REFUND]["count"] == rec["refunds_without_amount"] == 1
    assert groups[wm.KIND_MISSING_PAID_TOTAL]["count"] == 1
    stated = {wm.parse_order_warning(w).kind: wm.parse_order_warning(w).count
              for w in summary["warnings"] if wm.parse_order_warning(w).count is not None}
    assert stated == {kind: groups[kind]["count"] for kind in stated}
    for group in summary["warnings_detail"]:
        assert group["count"] == len(group["items"])


def test_clean_analysis_has_no_groups_and_the_flat_list_is_still_there():
    summary = analyze(scenario.orders(), scenario.returns(), scenario.classifier(), 50000, "x").summary
    assert summary["warnings"] == [] and summary["warnings_detail"] == []


# --- config/avertismente.json ----------------------------------------------------------------

def _write_texts(tmp_path, mutate):
    data = copy.deepcopy(json.loads(WARNING_TEXTS_FILE.read_text(encoding="utf-8")))
    mutate(data)
    path = tmp_path / "avertismente.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_shipped_config_has_every_group_with_plain_romanian_texts():
    assert set(TEXTS["grupe"]) == set(wm.ALL_KINDS)
    for kind, group in TEXTS["grupe"].items():
        assert all(group[key].strip() for key in ("title", "explanation", "what_to_do", "item_text")), kind
        assert isinstance(group["affects_totals"], bool)
    assert TEXTS["grupe"][wm.KIND_PENDING_RETURN]["affects_totals"] is True


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d["grupe"].pop("other"), "lipsește grupa 'other'"),
    (lambda d: d["grupe"]["other"].update(item_text="{necunoscut}"), "câmpuri necunoscute"),
    (lambda d: d["grupe"]["other"].update(item_text="{text!r}"), "câmpuri simple"),
    (lambda d: d["grupe"]["other"].update(item_text="{text.x}"), "câmpuri simple"),
    (lambda d: d["grupe"]["other"].update(item_text="{text"), "acolade greșite"),
    (lambda d: d["grupe"]["other"].update(affects_totals="da"), "true sau false"),
    (lambda d: d["grupe"]["other"].update(title="  "), "textul nevid 'title'"),
    (lambda d: d["grupe"]["other"].pop("what_to_do"), "textul nevid 'what_to_do'"),
    (lambda d: d.pop("valori_implicite"), "'valori_implicite'"),
    (lambda d: d["valori_implicite"].update(produse_in_plus="încă {altceva}"), "{count}"),
    (lambda d: d["etichete_status"].update(DELIVERED=5), "'etichete_status'"),
])
def test_a_wrong_config_is_rejected_with_the_file_and_the_reason(tmp_path, mutate, expected):
    path = _write_texts(tmp_path, mutate)
    with pytest.raises(ValueError) as error:
        load_warning_texts(path)
    assert expected in str(error.value) and "avertismente.json" in str(error.value)


def test_a_config_with_broken_json_names_the_file_line_and_column(tmp_path):
    path = tmp_path / "avertismente.json"
    path.write_text('{"grupe": ', encoding="utf-8")
    with pytest.raises(ValueError, match="avertismente.json.*linia 1"):
        load_warning_texts(path)


def test_a_config_that_is_not_an_object_is_rejected(tmp_path):
    path = tmp_path / "avertismente.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="avertismente.json"):
        load_warning_texts(path)


# --- cache-uri salvate de o versiune veche ---------------------------------------------------------

def _stale_order():
    """Comandă salvată de parserul vechi: mesajul „lipsește Total platit” apare și pentru blocul anulat."""
    cancelled = _block("Vanzator Alfa SRL", block_status.CANCELLED, paid=None)
    delivered_same_seller = _block("Vanzator Alfa SRL", block_status.DELIVERED, paid=None)
    delivered_other = _block("Firma Beta SRL", block_status.DELIVERED, paid=None)
    order = _order("100700001", "2026-01-01T10:00", cancelled, delivered_same_seller, delivered_other, header=0)
    order.warnings = [
        wm.format_missing_paid_total("100700001", "Vanzator Alfa SRL"),  # blocul anulat
        wm.format_missing_paid_total("100700001", "Vanzator Alfa SRL"),  # blocul livrat al aceluiași vânzător
        wm.format_missing_paid_total("100700001", "Firma Beta SRL"),
        wm.format_no_products("100700001", "Firma Beta SRL"),
    ]
    return order


def test_stale_missing_paid_total_messages_of_cancelled_blocks_are_dropped_one_per_cancelled_block():
    kept = current_order_warnings(_stale_order())
    assert kept == [
        wm.format_missing_paid_total("100700001", "Vanzator Alfa SRL"),
        wm.format_missing_paid_total("100700001", "Firma Beta SRL"),
        wm.format_no_products("100700001", "Firma Beta SRL"),
    ]


def test_an_order_without_cancelled_blocks_keeps_all_its_warnings_untouched():
    order = _order("100700002", "2026-01-01T10:00", _block(paid=None), header=0)
    order.warnings = [wm.format_missing_paid_total("100700002", "Vanzator Alfa SRL"), "un mesaj oarecare"]
    assert current_order_warnings(order) == order.warnings
    assert current_order_warnings(_order("100700003", None)) == []


def test_analysis_of_a_stale_cache_does_not_show_the_old_cancelled_block_noise():
    stale = _stale_order()
    summary = analyze([stale], [], scenario.classifier(), 50000, "x").summary
    missing = [w for w in summary["warnings"] if "Total platit" in w]
    assert len(missing) == 2 and stale.warnings[0] in missing  # două mesaje (livrat + Firma Beta), nu trei
    group = _by_kind(summary["warnings_detail"])[wm.KIND_MISSING_PAID_TOTAL]
    assert group["count"] == 2 and {i["seller"] for i in group["items"]} == {"Vanzator Alfa SRL", "Firma Beta SRL"}
    assert all(i["status"] == TEXTS["etichete_status"][block_status.DELIVERED] for i in group["items"])


def test_two_blocks_of_one_seller_without_a_paid_total_get_their_own_statuses_in_message_order():
    delivered = _block("Vanzator Alfa SRL", block_status.DELIVERED, paid=None)
    in_progress = _block("Vanzator Alfa SRL", block_status.IN_PROGRESS, paid=None)
    order = _order("100700004", "2026-01-01T10:00", delivered, in_progress, header=0)
    warnings = [wm.format_missing_paid_total("100700004", "Vanzator Alfa SRL")] * 2
    group = _by_kind(build_warnings_detail(warnings, [order], [], [], TEXTS))[wm.KIND_MISSING_PAID_TOTAL]
    assert [i["status"] for i in group["items"]] == [
        TEXTS["etichete_status"][block_status.DELIVERED], TEXTS["etichete_status"][block_status.IN_PROGRESS]]


def test_header_mismatch_row_explains_the_usual_cause_only_for_orders_with_a_cancelled_block():
    with_cancelled = _order("100800001", "2026-02-01T10:00", _block(paid=5000), _block("Firma Beta SRL", block_status.CANCELLED, paid=None),
                            header=7000)
    without = _order("100800002", "2026-02-02T10:00", _block(paid=5000), header=7000)
    mismatches = [{"order_id": "100800001", "header_bani": 7000, "blocks_bani": 5000},
                  {"order_id": "100800002", "header_bani": 7000, "blocks_bani": 5000}]
    group = _by_kind(build_warnings_detail([], [with_cancelled, without], [], mismatches, TEXTS))[wm.KIND_HEADER_MISMATCH]
    first, second = group["items"]
    assert first["text"] == f"total din antet 70,00 Lei, suma blocurilor 50,00 Lei; {TEXTS['valori_implicite']['antet_cu_bloc_anulat']}"
    assert second["text"] == "total din antet 70,00 Lei, suma blocurilor 50,00 Lei"


def test_a_config_without_the_cancelled_block_hint_is_rejected(tmp_path):
    path = _write_texts(tmp_path, lambda d: d["valori_implicite"].pop("antet_cu_bloc_anulat"))
    with pytest.raises(ValueError, match="antet_cu_bloc_anulat"):
        load_warning_texts(path)


def test_a_missing_paid_total_message_for_an_order_that_is_not_in_the_list_still_gets_a_readable_status():
    group = _by_kind(build_warnings_detail([wm.format_missing_paid_total("100900001", "Firma Beta SRL")], [], [], [], TEXTS))[
        wm.KIND_MISSING_PAID_TOTAL]
    (item,) = group["items"]
    assert item["status"] == TEXTS["etichete_status"][block_status.UNKNOWN] and "()" not in item["text"]
    assert item["placed_at"] is None and item["order_ids"] == ["100900001"]


def test_a_message_from_the_current_parser_is_kept_even_if_the_same_seller_also_has_a_cancelled_block_without_a_total():
    # parserul nou emite UN mesaj (pentru blocul livrat); nu are voie să-l piardă din cauza blocului anulat
    order = _order("100700005", "2026-01-01T10:00", _block("Vanzator Alfa SRL", block_status.CANCELLED, paid=None),
                   _block("Vanzator Alfa SRL", block_status.DELIVERED, paid=None), header=0)
    order.warnings = [wm.format_missing_paid_total("100700005", "Vanzator Alfa SRL")]
    assert current_order_warnings(order) == order.warnings


def test_a_message_about_a_seller_with_no_cancelled_block_is_never_dropped():
    order = _order("100700006", "2026-01-01T10:00", _block("Vanzator Alfa SRL", paid=1000), header=1000)
    order.warnings = [wm.format_missing_paid_total("100700006", "Altcineva SRL")] * 2  # vânzător necunoscut în comandă
    assert current_order_warnings(order) == order.warnings

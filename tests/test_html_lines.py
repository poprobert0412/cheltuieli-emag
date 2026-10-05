"""Teste pentru transformarea HTML -> linii de text."""

from emag_spend.html_lines import html_to_lines


def test_block_elements_split_lines():
    assert html_to_lines("<div>a<div>b</div>c</div>") == ["a", "b", "c"]


def test_inline_spans_join_into_one_line_like_money_markup():
    html = (
        '<p><span class="money-int">222</span><sup class="money-decimal">'
        '<small>,</small>98</sup> <span class="money-currency">Lei</span></p>'
    )
    assert html_to_lines(html) == ["222,98 Lei"]


def test_label_and_value_spans_share_a_line():
    html = "<p><span>Total produse:</span> <span>10,00 Lei</span></p>"
    assert html_to_lines(html) == ["Total produse: 10,00 Lei"]


def test_script_style_and_comments_are_ignored():
    html = "<body><script>var a='Total 1,00 Lei'</script><style>p{}</style><!-- ascuns --><p>vizibil</p></body>"
    assert html_to_lines(html) == ["vizibil"]


def test_source_newlines_inside_a_block_do_not_split_lines():
    assert html_to_lines("<p>Total\n    produse:\n   </p>") == ["Total produse:"]


def test_links_and_buttons_are_separate_lines():
    html = '<div><span>Produse ridicate</span><a href="#">Istoric livrare</a></div>'
    assert html_to_lines(html) == ["Produse ridicate", "Istoric livrare"]


def test_br_splits_lines():
    assert html_to_lines("<p>Data de livrare:<br><strong>27 mai 2026</strong></p>") == ["Data de livrare:", "27 mai 2026"]


def test_empty_and_whitespace_only_pages():
    assert html_to_lines("") == []
    assert html_to_lines("<div>  \n  </div>") == []


def test_deeply_nested_html_does_not_crash():
    html = "<div>" * 300 + "adanc" + "</div>" * 300
    assert html_to_lines(html) == ["adanc"]

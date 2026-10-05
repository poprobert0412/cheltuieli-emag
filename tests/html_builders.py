"""Construiește pagini HTML INVENTATE care imită structura paginilor eMAG.

Folosit doar de teste. Nicio dată reală: numele, adresele și sumele sunt
inventate. Paginile conțin intenționat un nume, un telefon și un e-mail
FALSE în secțiunile de contact, ca testele să verifice că parserele nu le
iau. Două așezări posibile pentru etichetă+valoare ("inline": în același
<p>; "stacked": în elemente-bloc separate), ca parserul să nu depindă de
una singură.
"""

FAKE_NAME = "Nume Fictiv"
FAKE_PHONE = "0700000000"
FAKE_EMAIL = "fictiv@example.test"
FAKE_ADDRESS = "Strada Inventata nr. 1"


def money(text: str) -> str:
    """Suma ca în pagina eMAG: întreg, zecimale în <sup>, apoi 'Lei'. Ex. '222,98' sau '-34,00'."""
    whole, _, frac = text.partition(",")
    return (
        f'<span class="money-int">{whole}</span>'
        f'<sup class="money-decimal"><small class="mf-decimal">,</small>{frac}</sup> '
        f'<span class="money-currency">Lei</span>'
    )


def _label_value(label: str, value_html: str, layout: str) -> str:
    if layout == "stacked":
        return f'<div class="row"><div class="go-left">{label}</div><div class="go-right">{value_html}</div></div>'
    return f'<p><span class="go-left">{label}</span> <span class="go-right">{value_html}</span></p>'


def block_html(block: dict, layout: str = "inline") -> str:
    """Un bloc de vânzător. Chei: header, status (listă), storno, items, total_products,
    vouchers, shipping, services, other (listă de (eticheta, suma)), seller_label, paid
    (sau `to_pay` = „Total de plata”, ca la blocurile anulate)."""
    status = "".join(f'<span class="status-message-title">{s}</span>' for s in block["status"])
    storno = f'<a class="full-white-button">Factura storno 100200300</a>' if block.get("storno") else ""
    items = ""
    for row in block["items"]:
        name, price, qty = row[:3]
        if len(row) > 4 and row[4]:  # rând "Pachet": row[4] = componentele
            components = "".join(
                f'<li><div class="product-details-wrapper"><div class="product-details"><p class="product-description">{c}</p></div></div></li>'
                for c in row[4]
            )
            items += (
                '<li class="promo-bundle clearfix"><div class="promo-heading-wrapper"><span class="promo-heading">Pachet</span>'
                f'<div class="order-item-price-box"><p class="order-items-price">{money(price)}</p>'
                f'<span class="product-quantity">{qty} buc</span></div></div>'
                f'<ul class="promo-bundle-contents">{components}</ul></li>'
            )
            continue
        attribute = f'<a class="warranty-type">{row[3]}</a>' if len(row) > 3 else ""
        items += (
            '<li class="clearfix"><a class="go-left"><img class="product-img"></a>'
            f'<div class="product-details go-left"><p class="product-description">{name}</p>'
            f'{attribute}<a class="rate">Acorda o nota</a></div>'
            f'<div class="go-right"><p class="order-items-price">{money(price)}</p>'
            f'<span class="product-quantity">{qty} buc</span></div></li>'
        )
    totals = _label_value("Total produse:", money(block["total_products"]), layout)
    for voucher in block.get("vouchers", []):
        totals += _label_value("Reducere conform voucher/card cadou:", money(voucher), layout)
    if "shipping" in block:
        shipping = block["shipping"]
        totals += _label_value("Cost livrare:", "GRATUIT" if shipping == "GRATUIT" else money(shipping), layout)
    for service in block.get("services", []):
        totals += _label_value("Servicii operationale::", money(service), layout)
    for label, amount in block.get("other", []):
        totals += _label_value(label, money(amount), layout)
    if "paid" in block:
        totals += _label_value(f"Total platit {block['seller_label']}:", money(block["paid"]), layout)
    if "to_pay" in block:  # bloc anulat: eMAG arată „Total de plata” (suma de plătit), nu „Total platit”
        totals += _label_value(f"Total de plata {block['seller_label']}:", money(block["to_pay"]), layout)
    return (
        f'<h2 class="order-hist-title">{block["header"]}</h2>'
        '<div class="order-hist-box clearfix">'
        f'<div class="order-shipping-status"><div class="go-right right-col">{status}'
        '<a class="full-blue-button">Istoric livrare</a><p>Data de livrare:<br><strong>27 mai 2026</strong></p></div></div>'
        '<div class="order-details-box"><p class="title">Modalitate livrare:</p><p>Ridicare personala din easybox Test</p>'
        f'<p>Pentru:</p><p>{FAKE_NAME}, {FAKE_PHONE}</p><p>Adresa:</p><p>{FAKE_ADDRESS}</p></div>'
        f'<div class="order-details-box"><p class="title">Date facturare</p><p>Pentru:</p><p>{FAKE_NAME}</p></div>'
        f'{storno}<a class="full-white-button">Factura 100200301</a></div>'
        f'<div class="order-items"><ul class="product-list">{items}</ul>{totals}</div>'
    )


def order_page(order_id: str, placed: str, header_total: str | None, blocks: list[dict], layout: str = "inline") -> str:
    """Pagina de detalii a unei comenzi (cu meniul de cont, ca în realitate)."""
    total = f'<p>Total: {money(header_total)}</p>' if header_total else ""
    body = "".join(block_html(b, layout) for b in blocks)
    return (
        "<html><head><title>Contul tau</title><script>var x = 'Total produse: 1,00 Lei';</script></head><body>"
        '<nav><a>Comenzile mele</a><a>Log out</a></nav>'
        f'<span class="account_holder"><h1 class="order-hist-title">Comanda nr. {order_id}</h1>'
        f'<div class="order-hist-box"><p>Plasata pe: <strong>{placed}</strong></p>{total}</div>'
        f"{body}</span></body></html>"
    )


def return_page(
    return_id: str,
    products: list[str],
    steps: list[tuple[str, str]],
    order_ids: list[str],
    refund_text: str = "",
    mode: str = "Vreau banii inapoi",
    merge_title_and_date: bool = False,
    future_steps: list[str] | None = None,
) -> str:
    """Pagina de detalii a unui retur. `steps` = [(titlu, 'Data: 1 Iulie, 13:44'), ...];
    `future_steps` = titluri de pași încă neefectuați, afișați fără dată (ca în pagina reală)."""
    product_html = "".join(f"<p>{p}</p>" for p in products)
    if merge_title_and_date:
        steps_html = "".join(f"<div><span>{t}</span> <span>{d}</span></div>" for t, d in steps)
    else:
        steps_html = "".join(f"<div><p>{t}</p><p>{d}</p></div>" for t, d in steps)
    steps_html += "".join(f"<div><p>{t}</p></div>" for t in (future_steps or []))
    refund = f"<p>{refund_text}</p>" if refund_text else ""
    orders_html = "".join(f"<p>#{o}</p><p>Produs vandut de eMAG</p>" for o in order_ids)
    return (
        "<html><body><nav><a>Retururile mele</a></nav><main>"
        f"<h1>Retur #{return_id}</h1><div><h2>Detalii comanda</h2>{product_html}</div>"
        f"<div><h2>Status retur</h2>{steps_html}{refund}"
        "<p>Foloseste codul PIN de mai jos.</p><p>Cod PIN:</p><p>ABC123</p></div>"
        "<div><h2>Detalii de contact</h2><p>Nume</p>"
        f"<p>{FAKE_NAME}</p><p>Email</p><p>{FAKE_EMAIL}</p><p>Numar de telefon</p><p>{FAKE_PHONE}</p>"
        f"<p>Adresa</p><p>{FAKE_ADDRESS}</p></div>"
        "<div><h2>Detalii cerere retur</h2><p>Data retur</p><p>01.07.2026</p>"
        f"<p>Modalitate predare produs</p><p>easybox</p><p>Modalitate restituire</p><p>{mode}</p></div>"
        f"<div><p>Produse din comanda:</p>{orders_html}</div>"
        "<div><h3>Istoricul tau de navigare</h3></div></main></body></html>"
    )

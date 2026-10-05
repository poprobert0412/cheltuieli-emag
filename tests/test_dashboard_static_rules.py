"""Reguli verificate direct pe sursa componentei dashboard (fără browser): CSS scopat, tokeni, JS curat, șablon corect."""

import re

import pytest

from emag_spend import settings

CSS = settings.DASHBOARD_CSS_FILE.read_text(encoding="utf-8")
JS = settings.DASHBOARD_JS_FILE.read_text(encoding="utf-8")
TEMPLATE = settings.REPORT_TEMPLATE_FILE.read_text(encoding="utf-8")

LIGHT = ".emag-dash"
DARK_AUTO = ':root:not([data-theme="light"]) .emag-dash'
DARK_FORCED = ':root[data-theme="dark"] .emag-dash'
AT_RULES_WITH_RULES = ("@media", "@container", "@supports")
WCAG_AA_TEXT = 4.5
WCAG_AA_GRAPHICS = 3.0


# ---------- un parser CSS minimal (suficient pentru fișierul nostru) ----------

def _parse(text):
    """Împarte CSS fără comentarii în (prelude, corp, copii); at-rule-urile cu reguli au copii."""
    rules, i = [], 0
    while True:
        j = text.find("{", i)
        if j < 0:
            return rules
        depth, k = 1, j + 1
        while depth and k < len(text):
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            k += 1
        prelude, body = text[i:j].strip(), text[j + 1:k - 1]
        children = _parse(body) if prelude.startswith(AT_RULES_WITH_RULES) else None
        rules.append((prelude, body, children))
        i = k


def _flatten(rules, context=()):
    """Produce (context, selector, body) pentru fiecare regulă, intrând în @media/@container/@supports."""
    for prelude, body, children in rules:
        if children is None:
            yield context, prelude, body
        else:
            yield from _flatten(children, context + (prelude,))


CSS_RULES = list(_flatten(_parse(re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))))


def _tokens(selector, context=()):
    """Toți tokenii --ed-* definiți de regulile cu acest selector (și context), ca dict nume -> valoare."""
    found = {}
    for ctx, sel, body in CSS_RULES:
        if sel == selector and ctx == context:
            found.update(dict(re.findall(r"(--ed-[\w-]+)\s*:\s*([^;]+);", body)))
    return found


DARK_CONTEXT = ("@media (prefers-color-scheme: dark)",)
LIGHT_TOKENS = _tokens(LIGHT)
DARK_AUTO_TOKENS = _tokens(DARK_AUTO, DARK_CONTEXT)
DARK_FORCED_TOKENS = _tokens(DARK_FORCED)


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---------- CSS ----------

def test_every_css_selector_is_scoped_under_emag_dash():
    unscoped = []
    for _, selector, _ in CSS_RULES:
        for part in (p.strip() for p in selector.split(",")):
            if not part.startswith((LIGHT, DARK_AUTO, DARK_FORCED)):
                unscoped.append(part)
    assert unscoped == []


def test_every_css_class_has_the_ed_prefix():
    foreign = set()
    for _, selector, _ in CSS_RULES:
        foreign |= {c for c in re.findall(r"\.([A-Za-z_][\w-]*)", selector) if c != "emag-dash" and not c.startswith("ed-")}
    assert foreign == set()


def test_dark_variants_are_identical_and_cover_every_light_color_override():
    assert DARK_AUTO_TOKENS, "lipsește varianta întunecată automată (prefers-color-scheme)"
    assert DARK_AUTO_TOKENS == DARK_FORCED_TOKENS, "cele două reguli întunecate trebuie să aibă aceiași tokeni"
    missing = [t for t in DARK_AUTO_TOKENS if t not in LIGHT_TOKENS]
    assert missing == []
    for must_override in ("--ed-page", "--ed-surface", "--ed-ink", "--ed-ink-2", "--ed-muted", "--ed-border", "--ed-s1", "--ed-s2", "--ed-s3", "--ed-focus"):
        assert must_override in DARK_AUTO_TOKENS, must_override


def test_no_literal_colors_outside_the_token_blocks():
    token_selectors = {LIGHT, DARK_AUTO, DARK_FORCED}
    offenders = []
    for _, selector, body in CSS_RULES:
        in_token_block = selector in token_selectors and "--ed-ink:" in body
        if not in_token_block and re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", body):
            offenders.append(selector)
    assert offenders == []


def test_text_tokens_meet_wcag_aa_in_every_theme():
    for name, tokens in (("lumină", LIGHT_TOKENS), ("întuneric", {**LIGHT_TOKENS, **DARK_AUTO_TOKENS})):
        for text_token in ("--ed-ink", "--ed-ink-2", "--ed-muted", "--ed-danger"):
            for ground in ("--ed-page", "--ed-surface"):
                ratio = _contrast(tokens[text_token], tokens[ground])
                assert ratio >= WCAG_AA_TEXT, f"{name}: {text_token} pe {ground} = {ratio:.2f}"
        assert _contrast(tokens["--ed-note-ink"], tokens["--ed-note-bg"]) >= WCAG_AA_TEXT, f"{name}: banner"
        for ground in ("--ed-page", "--ed-surface"):
            assert _contrast(tokens["--ed-focus"], tokens[ground]) >= WCAG_AA_GRAPHICS, f"{name}: inel de focus pe {ground}"
        # starea „păstrat” (albastru) e linia principală din grafice: trebuie să se vadă pe fundal
        assert _contrast(tokens["--ed-s1"], tokens["--ed-surface"]) >= WCAG_AA_GRAPHICS, f"{name}: s1"


def _blend_over(rgba, ground_hex):
    """Culoarea rgba(r, g, b, a) pusă peste un fundal #rrggbb, ca hex: ce vede ochiul pe ecran."""
    r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", rgba))
    ground = [int(ground_hex[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = [round(c * a + back * (1 - a)) for c, back in zip((r, g, b), ground)]
    return "#" + "".join(f"{v:02x}" for v in mixed)


def test_button_outlines_meet_non_text_contrast_in_every_theme():
    # WCAG 1.4.11: conturul unui control trebuie să aibă 3:1 față de fundal (înainte: 2,0:1 în lumină, 2,9:1 în întuneric)
    for name, tokens in (("lumină", LIGHT_TOKENS), ("întuneric", {**LIGHT_TOKENS, **DARK_AUTO_TOKENS})):
        for ground in ("--ed-page", "--ed-surface"):
            outline = _blend_over(tokens["--ed-border-strong"], tokens[ground])
            ratio = _contrast(outline, tokens[ground])
            assert ratio >= WCAG_AA_GRAPHICS, f"{name}: contur pe {ground} = {ratio:.2f}"


def test_css_has_forced_colors_touch_target_and_focus_room_rules():
    forced = [body for context, _, body in CSS_RULES if context == ("@media (forced-colors: active)",)]
    assert forced and all("forced-color-adjust: none" in body or "border-color" in body for body in forced)
    selectors = " ".join(sel for context, sel, _ in CSS_RULES if context == ("@media (forced-colors: active)",))
    for needle in (".ed-funnel-seg", ".ed-bar-fill", ".ed-sw", '.ed-chip[aria-pressed="true"]', '.ed-toggle[aria-pressed="true"]'):
        assert needle in selectors, needle
    assert LIGHT_TOKENS["--ed-target"].strip() == "40px"
    assert CSS.count("min-height: var(--ed-target)") >= 2  # butoanele și rezumatele (summary)
    assert "scroll-margin-block: var(--ed-scroll-margin)" in CSS


def test_motion_rules_never_transition_all_and_respect_reduced_motion():
    assert not re.search(r"transition\s*:\s*all\b", CSS)
    assert not re.search(r"transition-property\s*:\s*all\b", CSS)
    assert "prefers-reduced-motion" in CSS
    for context, selector, body in CSS_RULES:
        if "transition" in body or "animation" in body:
            assert any("prefers-reduced-motion: no-preference" in c for c in context), selector


def test_outline_is_never_removed_without_a_replacement():
    for _, selector, body in CSS_RULES:
        if re.search(r"outline\s*:\s*(none|0)\b", body):
            assert "stroke" in body or "box-shadow" in body or "border" in body, selector


def test_css_has_the_interaction_and_layout_rules_the_guidelines_ask_for():
    for needle in ("touch-action: manipulation", "text-wrap: balance", ":focus-visible", "overflow-wrap: anywhere",
                   "min-width: 0", "font-variant-numeric: tabular-nums", "container-type: inline-size", "@media print"):
        assert needle in CSS, needle


def test_css_does_not_embed_forbidden_sequences_for_inline_use():
    lowered = CSS.lower()
    assert "</style" not in lowered and "<!--" not in lowered


# ---------- JS ----------

def _code_without_comments(js):
    no_block = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", no_block, flags=re.M)


JS_CODE = _code_without_comments(JS)


@pytest.mark.parametrize("pattern", [
    r"\.innerHTML", r"\.outerHTML", r"insertAdjacentHTML", r"document\.write", r"\beval\s*\(", r"new\s+Function",
    r"\bfetch\s*\(", r"XMLHttpRequest", r"sendBeacon", r"WebSocket", r"importScripts", r"document\.body",
    r"getElementById", r"localStorage", r"sessionStorage", r"document\.cookie", r"window\.open", r"\blocation\.",
])
def test_js_avoids_unsafe_or_global_apis(pattern):
    assert not re.search(pattern, JS_CODE), pattern


def test_js_never_sets_element_ids():
    assert not re.search(r"""setAttribute\(\s*['"]id['"]""", JS_CODE)
    assert not re.search(r"""['"]id['"]\s*:""", JS_CODE)
    assert not re.search(r"\.id\s*=", JS_CODE)


def test_js_is_a_classic_script_with_the_public_contract():
    assert "'use strict'" in JS_CODE
    assert not re.search(r"^\s*(import|export)\s", JS_CODE, re.M)
    assert "global.EmagDashboard = { version: VERSION, validate, mount }" in JS_CODE
    assert "const VERSION = '1'" in JS_CODE


def test_js_has_no_sequences_that_break_inline_embedding():
    lowered = JS.lower()
    assert "</script" not in lowered and "<!--" not in lowered


def test_js_strings_use_the_ellipsis_character_not_three_dots():
    single = r"'(?:[^'\\\n]|\\.)*'"
    double = r'"(?:[^"\\\n]|\\.)*"'
    literals = re.findall(f"{single}|{double}", JS_CODE)
    assert [lit for lit in literals if "..." in lit] == []  # spread-ul (...x) nu e între ghilimele


def test_js_declares_every_block_of_the_contract():
    blocks = ("hero", "funnel", "tiles", "categories", "highlights", "years", "big", "top", "preturi", "sellers", "excluded", "control", "method")
    for name in blocks:
        assert f"block('{name}'," in JS_CODE, name


# ---------- șablonul raportului ----------

def test_template_has_each_placeholder_exactly_once():
    for placeholder in ("/*__DASHBOARD_CSS__*/", "/*__DASHBOARD_JS__*/", "/*__DATE_ANALIZA__*/null"):
        assert TEMPLATE.count(placeholder) == 1, placeholder


def test_template_head_follows_the_guidelines():
    assert '<html lang="ro">' in TEMPLATE
    viewport = re.search(r'<meta name="viewport" content="([^"]*)"', TEMPLATE).group(1)
    assert "user-scalable" not in viewport and "maximum-scale" not in viewport
    assert re.search(r'<meta name="color-scheme" content="light dark">', TEMPLATE)
    colors = re.findall(r'<meta name="theme-color" content="#[0-9a-f]{6}" media="\(prefers-color-scheme: (light|dark)\)">', TEMPLATE)
    assert sorted(colors) == ["dark", "light"]
    assert "<title>Cheltuieli eMAG</title>" in TEMPLATE


def test_template_is_a_small_skeleton_with_theme_button_skip_link_and_noscript():
    assert len(TEMPLATE.splitlines()) < 140
    assert '<a class="rp-skip" href="#raport">' in TEMPLATE
    assert '<main id="raport">' in TEMPLATE and "<noscript>" in TEMPLATE
    assert 'translate="no">eMAG</span>' in TEMPLATE
    assert "EmagDashboard.mount(root, data)" in TEMPLATE
    assert "emag-tema" in TEMPLATE
    assert "http://" not in TEMPLATE and "https://" not in TEMPLATE

"""Calculul contrastului WCAG între culorile din app.css, fără browser.

Primește: valori de culoare CSS (#rgb, #rrggbb, rgb(), rgba()). Dă înapoi: raportul de contrast (1–21) între un text și un fundal,
cu fundalurile semitransparente așezate peste fundalul de dedesubt. Citește tokenii dintr-un fișier CSS cu `parse_token_blocks`.
Ce NU face: nu evaluează pagina randată (contrastul real din browser îl măsoară testele din test_app_ui_browser.py) și
nu cunoaște regulile de design; pragurile le hotărăște testul care îl cheamă.
"""

import re

HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
FUNCTION_COLOR = re.compile(r"^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*(?:,\s*([0-9.]+)\s*)?\)$")


def parse_color(text: str) -> tuple[float, float, float, float]:
    """(r, g, b, alfa) cu r, g, b în 0–255 și alfa în 0–1, dintr-o culoare CSS simplă."""
    value = text.strip()
    match = HEX_COLOR.match(value)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), 1.0
    match = FUNCTION_COLOR.match(value)
    if match:
        red, green, blue, alpha = match.groups()
        return float(red), float(green), float(blue), float(alpha) if alpha is not None else 1.0
    raise ValueError(f"culoare neînțeleasă: {text!r}")


def over(foreground: tuple, background: tuple) -> tuple[float, float, float, float]:
    """Culoarea `foreground` (cu alfa) așezată peste `background` (opac)."""
    alpha = foreground[3]
    return tuple(foreground[i] * alpha + background[i] * (1 - alpha) for i in range(3)) + (1.0,)


def luminance(color: tuple) -> float:
    """Luminanța relativă WCAG a unei culori opace."""
    def channel(value: float) -> float:
        """Un canal sRGB (0–255) liniarizat."""
        scaled = value / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast(foreground: str, background: str, under: str | None = None) -> float:
    """Raportul de contrast între text și fundal; `under` e fundalul de dedesubt când `background` e semitransparent."""
    back = parse_color(background)
    if back[3] < 1:
        back = over(back, parse_color(under if under is not None else "#ffffff"))
    front = over(parse_color(foreground), back)
    lighter, darker = sorted((luminance(front), luminance(back)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def parse_token_blocks(css: str) -> dict[str, dict[str, str]]:
    """Tokenii (`--nume: valoare`) din cele trei blocuri de temă: 'light' (:root), 'dark-auto' (media + :root:not) și 'dark' ([data-theme=dark])."""
    def tokens(block: str) -> dict[str, str]:
        """Perechile --nume: valoare dintr-un bloc de declarații."""
        return {name: value.strip() for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block)}

    light = re.search(r"^:root\s*\{(.*?)^\}", css, re.S | re.M)
    dark_auto = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{(.*?)^\s*\}\s*\}", css, re.S | re.M)
    dark = re.search(r"^:root\[data-theme=\"dark\"\]\s*\{(.*?)^\}", css, re.S | re.M)
    if not (light and dark_auto and dark):
        raise ValueError("nu găsesc cele trei blocuri de tokeni (:root, media dark, [data-theme=dark])")
    return {"light": tokens(light.group(1)), "dark-auto": tokens(dark_auto.group(1)), "dark": tokens(dark.group(1))}

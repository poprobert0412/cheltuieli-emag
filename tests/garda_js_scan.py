"""Despică un fișier JavaScript în trei vederi: cod pur, literale text și text fără comentarii.

Primește: textul unui fișier JS. Dă înapoi `JsViews`: `code` (comentariile, literalele și expresiile regulate
înlocuite cu spații, aceleași rânduri), `strings` (linie și text per literal, inclusiv șabloane cu backtick) și
`uncommented` (fără comentarii, cu literalele intacte). Există ca garda de rețea să caute tipare de COD (`fetch(`)
fără fals pozitiv pe texte care doar le menționează. Nu e un parser complet de JS; la îndoială, restul rândului
e privit ca cod (mai strict, nu mai slab).
"""

import re
from dataclasses import dataclass

# După aceste cuvinte, un `/` începe o expresie regulată (nu o împărțire): `return /x/.test(s)`.
REGEX_AFTER_WORDS = frozenset({"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"})
# După aceste caractere, un `/` începe o expresie regulată: `x = /a/`, `f(/a/)`, `[/a/]`, `!/a/.test(s)`.
REGEX_AFTER_CHARS = frozenset("(,=:[!&|?{};+-*%<>~^")
IDENTIFIER_CHAR = re.compile(r"[A-Za-z0-9_$]")


@dataclass
class JsViews:
    """Cele trei vederi ale unui fișier JS (vezi antetul modulului)."""

    code: str
    strings: list[tuple[int, str]]
    uncommented: str


def _blank(chunk: str) -> str:
    """Înlocuiește orice caracter în afară de sfârșitul de rând cu spațiu: păstrează numerele de linie."""
    return re.sub(r"[^\n]", " ", chunk)


class _Scanner:
    """Parcurge sursa o singură dată și umple cele trei vederi."""

    def __init__(self, source: str):
        """Pregătește sursa, poziția de citire și cele trei vederi, goale."""
        self.src = source
        self.pos = 0
        self.code: list[str] = []
        self.plain: list[str] = []  # fără comentarii, cu literale
        self.strings: list[tuple[int, str]] = []

    def _line(self, index: int) -> int:
        """Numărul liniei (de la 1) pentru poziția `index`."""
        return self.src.count("\n", 0, index) + 1

    def _emit(self, code_text: str, plain_text: str) -> None:
        """Adaugă același fragment în vederea de cod și în cea fără comentarii."""
        self.code.append(code_text)
        self.plain.append(plain_text)

    def run(self) -> JsViews:
        """Parcurge tot fișierul și întoarce vederile."""
        self._code(stop_at_close_brace=False)
        return JsViews("".join(self.code), self.strings, "".join(self.plain))

    def _skip_comment(self) -> bool:
        """Consumă un comentariu `//` sau `/* */` dacă începe aici; True dacă a consumat ceva."""
        if self.src.startswith("//", self.pos):
            end = self.src.find("\n", self.pos)
            end = len(self.src) if end < 0 else end
        elif self.src.startswith("/*", self.pos):
            end = self.src.find("*/", self.pos + 2)
            end = len(self.src) if end < 0 else end + 2
        else:
            return False
        self._emit(_blank(self.src[self.pos:end]), _blank(self.src[self.pos:end]))
        self.pos = end
        return True

    def _quoted(self) -> None:
        """Consumă un literal '...' sau "..." (se oprește și la sfârșit de rând, ca un literal nefinalizat să nu înghită fișierul)."""
        quote = self.src[self.pos]
        end = self.pos + 1
        while end < len(self.src) and self.src[end] not in (quote, "\n"):
            end += 2 if self.src[end] == "\\" else 1
        end = min(end, len(self.src))
        content = self.src[self.pos + 1:end]
        self.strings.append((self._line(self.pos), content))
        closing = self.src[end:end + 1] if self.src[end:end + 1] == quote else ""
        self._emit(quote + _blank(content) + closing, quote + content + closing)
        self.pos = end + len(closing)

    def _template_body(self) -> None:
        """Corpul unui șablon după backtick-ul de deschidere, până la backtick-ul de închidere."""
        chunk_start = self.pos
        chunk_line = self._line(self.pos)

        def flush(end: int) -> None:
            """Adaugă în `strings` bucata de șablon de la începutul ei până la `end`, dacă nu e goală."""
            if end > chunk_start:
                self.strings.append((chunk_line, self.src[chunk_start:end]))

        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if ch == "\\":
                self._emit(_blank(self.src[self.pos:self.pos + 2]), self.src[self.pos:self.pos + 2])
                self.pos += 2
            elif ch == "`":
                flush(self.pos)
                self._emit("`", "`")
                self.pos += 1
                return
            elif ch == "$" and self.src.startswith("${", self.pos):
                flush(self.pos)
                self._emit("${", "${")
                self.pos += 2
                self._code(stop_at_close_brace=True)
                self._emit("}", "}")
                self.pos += 1
                chunk_start, chunk_line = self.pos, self._line(self.pos)
            else:
                self._emit(" " if ch != "\n" else "\n", ch)
                self.pos += 1
        flush(self.pos)

    def _regex_literal(self) -> None:
        """Consumă o expresie regulată `/.../flags` (cu clase `[...]` în care `/` nu închide)."""
        end, in_class = self.pos + 1, False
        while end < len(self.src) and self.src[end] != "\n":
            ch = self.src[end]
            if ch == "\\":
                end += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                end += 1
                while end < len(self.src) and IDENTIFIER_CHAR.match(self.src[end]):
                    end += 1
                break
            end += 1
        self._emit(_blank(self.src[self.pos:end]), self.src[self.pos:end])
        self.pos = end

    def _code(self, stop_at_close_brace: bool) -> None:
        """Parcurge cod până la sfârșit sau (în `${}`) până la acolada care închide expresia."""
        depth, previous = 0, ""
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if self._skip_comment():
                continue
            if ch in "'\"":
                self._quoted()
                previous = "literal"
            elif ch == "`":
                self._emit("`", "`")
                self.pos += 1
                self._template_body()
                previous = "literal"
            elif ch == "/" and (previous in REGEX_AFTER_CHARS or previous in REGEX_AFTER_WORDS or previous == ""):
                self._regex_literal()
                previous = "literal"
            elif ch.isspace():
                self._emit(ch, ch)
                self.pos += 1
            elif IDENTIFIER_CHAR.match(ch):
                end = self.pos
                while end < len(self.src) and IDENTIFIER_CHAR.match(self.src[end]):
                    end += 1
                self._emit(self.src[self.pos:end], self.src[self.pos:end])
                previous = self.src[self.pos:end]
                self.pos = end
            else:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    if stop_at_close_brace and depth == 0:
                        return
                    depth -= 1
                self._emit(ch, ch)
                previous = ch
                self.pos += 1


def scan_js(source: str) -> JsViews:
    """Vederile `code`, `strings` și `uncommented` ale unui text JavaScript (vezi antetul)."""
    return _Scanner(source).run()

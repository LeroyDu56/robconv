"""ABB RAPID front-end: read a .mod/.modx/.sys/.sysx file into a nodes.Module."""

from dataclasses import dataclass
from pathlib import Path

from robconv.diagnostics import Diagnostic, Severity
from robconv.rapid import nodes
from robconv.rapid.parser import parse
from robconv.rapid.source import normalise_newlines, read_source

RAPID_SUFFIXES = frozenset({".mod", ".modx", ".sys", ".sysx", ".prg"})


@dataclass(frozen=True, slots=True)
class ParseResult:
    path: str
    encoding: str
    module: nodes.Module | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.module is not None and not any(d.severity is Severity.ERROR for d in self.diagnostics)


def parse_text(text: str, *, path: str = "<string>") -> ParseResult:
    module, diagnostics = parse(normalise_newlines(text))
    return ParseResult(path, "str", module, tuple(diagnostics))


def parse_file(path: str | Path) -> ParseResult:
    source = read_source(path)
    module, diagnostics = parse(source.text)
    return ParseResult(source.path, source.encoding, module, tuple(diagnostics))


__all__ = ["RAPID_SUFFIXES", "ParseResult", "nodes", "parse_file", "parse_text"]

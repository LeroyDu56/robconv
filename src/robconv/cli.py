"""Command-line interface.

    robconv parse FILE [--format pseudo|json] [-o OUT]
    robconv stats PATH [PATH ...]

`stats` parses every RAPID file under the given paths and reports what the V1
parser recognises versus what it leaves as Unsupported — the tool used to decide
what to support next on a real controller backup.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from robconv import __version__
from robconv.rapid import RAPID_SUFFIXES, ParseResult, parse_file
from robconv.rapid import nodes as n
from robconv.rapid.to_json import dumps, result_to_data
from robconv.rapid.to_pseudo import to_pseudo


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # Windows consoles default to cp1252
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args(argv)
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robconv", description="Industrial robot program converter (ABB RAPID -> FANUC TP).")
    parser.add_argument("--version", action="version", version=f"robconv {__version__}")
    sub = parser.add_subparsers(required=True, metavar="COMMAND")

    p_parse = sub.add_parser("parse", help="parse one RAPID module and print its AST")
    p_parse.add_argument("file", type=Path)
    p_parse.add_argument("--format", choices=("pseudo", "json"), default="pseudo")
    p_parse.add_argument("-o", "--output", type=Path, help="write to a file instead of stdout")
    p_parse.set_defaults(handler=_cmd_parse)

    p_stats = sub.add_parser("stats", help="coverage report over RAPID files or folders")
    p_stats.add_argument("paths", type=Path, nargs="+")
    p_stats.set_defaults(handler=_cmd_stats)
    return parser


def _cmd_parse(args: argparse.Namespace) -> int:
    try:
        result = parse_file(args.file)
    except OSError as exc:
        print(f"robconv: cannot read {args.file}: {exc}", file=sys.stderr)
        return 2

    for diag in result.diagnostics:
        print(f"{args.file}:{diag}", file=sys.stderr)

    if args.format == "json":
        output = dumps(result_to_data(result)) + "\n"
    elif result.module is not None:
        output = to_pseudo(result.module)
    else:
        output = ""

    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if result.ok else 1


def iter_rapid_files(paths: list[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.suffix.lower() in RAPID_SUFFIXES)
        else:
            yield path


def walk_statements(stmts: tuple[n.Stmt, ...]) -> Iterator[n.Stmt]:
    """Every statement, depth-first, including those nested in blocks."""
    for stmt in stmts:
        yield stmt
        match stmt:
            case n.If():
                for branch in stmt.branches:
                    yield from walk_statements(branch.body)
                yield from walk_statements(stmt.else_body)
            case n.For() | n.While():
                yield from walk_statements(stmt.body)
            case n.Test():
                for case in stmt.cases:
                    yield from walk_statements(case.body)
                yield from walk_statements(stmt.default or ())


def module_statements(result: ParseResult) -> Iterator[n.Stmt | n.ModuleItem]:
    if result.module is None:
        return
    for item in result.module.body:
        if isinstance(item, n.Routine):
            yield from walk_statements(item.body)
            yield from item.handlers
        else:
            yield item


def _cmd_stats(args: argparse.Namespace) -> int:
    nodes_count: Counter[str] = Counter()
    unsupported: Counter[str] = Counter()
    files = errors = 0
    for path in iter_rapid_files(args.paths):
        files += 1
        result = parse_file(path)
        file_errors = [d for d in result.diagnostics if d.severity.value == "error"]
        errors += len(file_errors)
        routines = len(result.module.routines) if result.module else 0
        print(f"{'OK ' if result.ok else 'ERR'}  {path}  ({routines} routines, {len(file_errors)} errors)")
        for diag in file_errors:
            print(f"       {diag}")
        for stmt in module_statements(result):
            nodes_count[type(stmt).__name__] += 1
            if isinstance(stmt, n.Unsupported):
                unsupported[stmt.kind] += 1

    print(f"\n{files} files, {errors} errors")
    print("\nStatements by node type:")
    for name, count in nodes_count.most_common():
        print(f"  {name:<14} {count:>6}")
    if unsupported:
        print("\nUnsupported by kind:")
        for kind, count in unsupported.most_common():
            print(f"  {kind:<18} {count:>6}")
    return 0 if errors == 0 else 1

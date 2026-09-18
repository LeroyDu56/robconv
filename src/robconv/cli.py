"""Command-line interface.

    robconv parse FILE [--format pseudo|json] [-o OUT]
    robconv stats PATH [PATH ...]
    robconv convert PATH [PATH ...] -o OUTDIR [--map mapping.json] [--routine NAME ...]

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
from robconv.convert import ConversionConfig, build_report, convert
from robconv.fanuc.ls_writer import write_ls
from robconv.rapid import RAPID_SUFFIXES, parse_file
from robconv.rapid import nodes as n
from robconv.rapid.eio import find_eio, read_eio
from robconv.rapid.to_json import dumps, result_to_data
from robconv.rapid.to_pseudo import to_pseudo
from robconv.rapid.walk import module_statements


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

    p_conv = sub.add_parser("convert", help="convert RAPID routines to FANUC .LS programs")
    p_conv.add_argument("paths", type=Path, nargs="+", help="RAPID files or folders (all modules share their data)")
    p_conv.add_argument("-o", "--output", type=Path, required=True, help="output folder")
    p_conv.add_argument("--map", type=Path, help="JSON mapping file (registers, I/O, frames...)")
    p_conv.add_argument(
        "--eio", type=Path,
        help="ABB EIO.cfg giving the signal types; default: found in the given folders or a SYSPAR folder next to them",
    )  # fmt: skip
    p_conv.add_argument(
        "--routine", action="append",
        help="convert only this PROC (repeatable); default: every PROC of non-system modules",
    )  # fmt: skip
    p_conv.set_defaults(handler=_cmd_convert)
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
        for stmt in module_statements(result.module):
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


def _cmd_convert(args: argparse.Namespace) -> int:
    modules = []
    sources = []
    texts: dict[str, str] = {}
    for path in iter_rapid_files(args.paths):
        result = parse_file(path)
        for diag in result.diagnostics:
            print(f"{path}:{diag}", file=sys.stderr)
        if not result.ok or result.module is None:
            print(f"robconv: {path} has syntax errors, fix them before converting", file=sys.stderr)
            return 1
        modules.append(result.module)
        sources.append(path.name)
        texts[result.module.name] = result.text
    if not modules:
        print("robconv: no RAPID file found", file=sys.stderr)
        return 2

    try:
        config = ConversionConfig.from_mapping_file(args.map) if args.map else ConversionConfig()
    except (OSError, ValueError, TypeError) as exc:  # json.JSONDecodeError is a ValueError
        print(f"robconv: invalid mapping file {args.map}: {exc}", file=sys.stderr)
        return 2
    eio_path = args.eio or find_eio(args.paths)
    signals = None
    if eio_path:
        try:
            signals = read_eio(eio_path)
        except OSError as exc:
            print(f"robconv: cannot read {eio_path}: {exc}", file=sys.stderr)
            return 2
        print(f"I/O signal types from {eio_path} ({len(signals)} signals)")
    result = convert(modules, config, args.routine, texts, signals)

    args.output.mkdir(parents=True, exist_ok=True)
    for info in result.programs:
        # newline="" keeps the CRLF produced by the writer, ASCII as on the controller.
        (args.output / f"{info.program.name}.LS").write_text(write_ls(info.program), encoding="ascii", newline="")
    report = args.output / "robconv_report.md"
    report.write_text(build_report(result, config, sources), encoding="utf-8")

    warnings = sum(1 for note in result.notes if note.kind == "WARNING")
    print(f"{len(result.programs)} programs written to {args.output}")
    print(f"{result.todo_count} TODO, {warnings} warnings: see {report}")
    return 0

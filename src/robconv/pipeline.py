"""Complete conversion of what the user drops, shared by the CLI and the desktop app.

    input (backup folder / .zip / files) -> Source -> one conversion per task -> output folder

Output layout, created next to the input unless an output folder is given:

    robconv_<name>/
      <task>/                   one folder per task of a backup (T_ROB1, T_ROB2...)
        *.LS
        robconv_report.md / .html
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from robconv.backup import Source, TaskSource, open_source
from robconv.convert import ConversionConfig, build_report, convert
from robconv.convert.html import markdown_to_html
from robconv.fanuc.ls_writer import write_ls
from robconv.rapid import ParseResult, parse_file
from robconv.rapid.eio import find_eio, read_eio

Log = Callable[[str], None]


@dataclass
class TaskOutput:
    task: str
    folder: Path
    programs: int = 0
    todo: int = 0
    warnings: int = 0
    syntax_errors: list[str] = field(default_factory=list)
    report_html: Path | None = None


@dataclass
class RunOutput:
    source_name: str
    kind: str
    folder: Path
    tasks: list[TaskOutput]
    eio: Path | None

    @property
    def programs(self) -> int:
        return sum(t.programs for t in self.tasks)

    @property
    def todo(self) -> int:
        return sum(t.todo for t in self.tasks)


def unique_folder(base: Path) -> Path:
    """base, or base_2, base_3... : never write into a previous run's output."""
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = base.with_name(f"{base.name}_{n}")
    return candidate


def _convert_task(task: TaskSource, folder: Path, config: ConversionConfig, signals, routines,
                  source: Source, log: Log) -> TaskOutput:  # fmt: skip
    out = TaskOutput(task.name, folder)
    parsed: list[ParseResult] = []
    for path in task.files:
        result = parse_file(path)
        if result.module is None:
            out.syntax_errors.append(f"{path.name}: not a RAPID module ({result.diagnostics[0].message})")
            continue
        out.syntax_errors += [f"{path.name}:{d}" for d in result.diagnostics if d.severity.value == "error"]
        parsed.append(result)
    program_names = {r.module.name.upper() for r in parsed if Path(r.path) in set(task.program_files)}

    result = convert(
        [p.module for p in parsed], config, routines,
        sources={p.module.name: p.text for p in parsed}, signals=signals,
        program_modules=program_names if source.kind == "backup" else None,
    )  # fmt: skip
    folder.mkdir(parents=True, exist_ok=True)
    for info in result.programs:
        (folder / f"{info.program.name}.LS").write_text(write_ls(info.program), encoding="ascii", newline="")
    report = build_report(result, config, [Path(p.path).name for p in parsed])
    if out.syntax_errors:
        report += "\n## Syntax errors (statements skipped by the parser)\n\n"
        report += "\n".join(f"- `{e}`" for e in out.syntax_errors) + "\n"
    (folder / "robconv_report.md").write_text(report, encoding="utf-8")
    out.report_html = folder / "robconv_report.html"
    out.report_html.write_text(markdown_to_html(report, f"robconv - {source.name} - {task.name}"), encoding="utf-8")

    out.programs = len(result.programs)
    out.todo = result.todo_count
    out.warnings = sum(1 for n in result.notes if n.kind == "WARNING")
    log(f"  {task.name}: {out.programs} programs, {out.todo} TODO, {out.warnings} warnings"
        + (f", {len(out.syntax_errors)} syntax errors" if out.syntax_errors else ""))  # fmt: skip
    return out


def run(
    paths: list[Path],
    output: Path | None = None,
    config: ConversionConfig | None = None,
    routines: list[str] | None = None,
    eio: Path | None = None,
    log: Log = print,
) -> RunOutput:
    config = config or ConversionConfig()
    with open_source(paths) as source:
        if not any(task.files for task in source.tasks):
            raise ValueError("no RAPID module found (.mod, .modx, .sys, .sysx, .prg)")
        location = source.location or Path.cwd()
        folder = output or unique_folder(location / f"robconv_{source.name}")
        eio_path = eio or source.eio or (find_eio([Path(p) for p in paths]) if source.kind == "files" else None)
        signals = read_eio(eio_path) if eio_path else None

        what = "ABB backup" if source.kind == "backup" else "RAPID files"
        log(f"{what} '{source.name}': {len(source.tasks)} task(s)")
        if eio_path:
            log(f"I/O signal types from {eio_path.name} ({len(signals or {})} signals)")
        tasks = []
        for task in source.tasks:
            task_folder = folder / task.name if source.kind == "backup" else folder
            tasks.append(_convert_task(task, task_folder, config, signals, routines, source, log))
        log(f"Output: {folder}")
        return RunOutput(source.name, source.kind, folder, tasks, eio_path)

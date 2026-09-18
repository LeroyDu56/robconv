"""ConversionResult -> Markdown report (robconv_report.md).

The report is what the integrator works from on site: which frames, registers
and I/O numbers the programs expect, which heuristics were applied, and every
RAPID line that still needs manual work.
"""

from robconv import __version__
from robconv.convert.config import ConversionConfig
from robconv.convert.translate import Allocation, ConversionResult, FrameInfo
from robconv.fanuc.tp import CartesianPosition


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows]
    return out + [""]


def _frame_rows(frames: list[FrameInfo]) -> list[list[str]]:
    rows = []
    for f in frames:
        if f.frame is None or f.problem:
            rows.append([str(f.number), f.rapid_name, "—", "—", f.problem])
            continue
        (x, y, z), (w, p, r) = f.frame.pose.pos, f.frame.pose.wpr()
        rows.append([
            str(f.number), f.rapid_name,
            f"{x:.3f}, {y:.3f}, {z:.3f}", f"{w:.3f}, {p:.3f}, {r:.3f}", "",
        ])  # fmt: skip
    return rows


def _allocation_rows(allocations: list[Allocation], prefix: str) -> list[list[str]]:
    return [
        [f"{prefix}[{a.number}]", a.rapid_name, "mapping file" if a.fixed else "automatic", a.detail]
        for a in allocations
    ]


def build_report(result: ConversionResult, config: ConversionConfig, sources: list[str]) -> str:
    lines = [
        "# robconv conversion report",
        "",
        f"- Generated: {config.timestamp:%Y-%m-%d %H:%M:%S} by robconv {__version__}",
        f"- Sources: {', '.join(f'`{s}`' for s in sources)}",
        (
            f"- Programs: {len(result.programs)}, items to review: "
            f"{result.todo_count} TODO, {sum(1 for x in result.notes if x.kind == 'WARNING')} warnings"
        ),
        "",
        "> The `.LS` files are text listings to load and check in ROBOGUIDE (or convert on the controller).",
        "> They are **not** directly executable: frames, registers, I/O numbers and every TODO below",
        "> must be reviewed by the integrator before running on a robot.",
        "",
        "## Programs",
        "",
    ]
    rows = []
    for info in result.programs:
        todo = sum(1 for x in result.notes if x.program == info.program.name and x.kind == "TODO")
        rows.append([
            f"`{info.program.name}.LS`", f"{info.module}.{info.routine}",
            str(len(info.program.lines)), str(len(info.points)), str(todo),
        ])  # fmt: skip
    lines += _table(["TP program", "RAPID routine", "Lines", "Points", "TODO"], rows)

    if result.skipped_routines:
        lines += ["### Routines not converted", ""]
        lines += _table(["RAPID routine", "Reason"], [[f"{m}.{r}", why] for m, r, why in result.skipped_routines])

    lines += [
        "## Frames to set up on the controller",
        "",
        "Values are the RAPID frames converted to FANUC X, Y, Z (mm) and W, P, R (deg).",
        "User frames are `uframe x oframe` of the work object, relative to the robot world frame.",
        "",
        "### User frames (UFRAME)",
        "",
    ]
    lines += _table(["UF", "RAPID wobjdata", "X, Y, Z", "W, P, R", "Problem"], _frame_rows(result.uframes))
    lines += ["### Tool frames (UTOOL)", ""]
    lines += _table(["UT", "RAPID tooldata", "X, Y, Z", "W, P, R", "Problem"], _frame_rows(result.utools))

    lines += ["## Registers, flags and I/O", ""]
    lines += [
        (
            "Automatic numbers start at 1: pin them with a mapping file (`--map`) to avoid clashing with"
            " registers and I/O already used on the controller."
        ),
        "",
    ]
    lines += _table(["TP", "RAPID name", "Number from", "Note"],
                    _allocation_rows(result.registers, "R") + _allocation_rows(result.flags, "F")
                    + _allocation_rows(result.digital_outputs, "DO")
                    + _allocation_rows(result.digital_inputs, "DI")
                    + _allocation_rows(result.group_outputs, "GO")
                    + _allocation_rows(result.group_inputs, "GI"))  # fmt: skip

    lines += [
        "## Speed and zone mapping",
        "",
        (
            f"- Joint moves: `%` = RAPID TCP speed / {config.joint_speed_ref_mm_s:g} mm/s "
            "(`joint_speed_ref_mm_s`), clamped to 1-100 %. There is no exact equivalent: tune on the robot."
        ),
        (
            f"- Zones: `CNT` = zone radius (mm) x {config.cnt_per_mm:g} (`cnt_per_mm`), max 100. "
            "RAPID zones are distances, FANUC CNT is a percentage: approximate."
        ),
        "",
    ]
    lines += _table(["RAPID speed", "Motion", "TP"], [[s, m, t] for (s, m), t in sorted(result.speeds.items())])
    lines += _table(["RAPID zone", "TP"], [[z, t] for z, t in sorted(result.zones.items())])

    lines += ["## Points", ""]
    for info in result.programs:
        if not info.points:
            continue
        lines += [f"### {info.program.name}", ""]
        rows = []
        for p in info.points:
            if isinstance(p.value, CartesianPosition):
                v = p.value
                value = f"X {v.x:.3f} Y {v.y:.3f} Z {v.z:.3f} W {v.w:.3f} P {v.p:.3f} R {v.r:.3f}"
            else:
                value = "J " + " ".join(f"{j:.3f}" for j in p.value.joints)
            rows.append([f"P[{p.number}]", f"`{p.source}`", str(p.rapid_line), f"{p.uf}/{p.ut}", value])
        lines += _table(["P", "RAPID target", "RAPID line", "UF/UT", "Value"], rows)

    lines += ["## Items to review", ""]
    rows = [
        [x.program or "—", str(x.rapid_line) if x.rapid_line else "—", x.kind, x.message]
        for x in sorted(result.notes, key=lambda x: (x.program, x.rapid_line or 0))
    ]
    lines += _table(["Program", "RAPID line", "Kind", "Detail"], rows)
    return "\n".join(lines).rstrip() + "\n"

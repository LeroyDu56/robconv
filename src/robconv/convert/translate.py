"""RAPID AST -> FANUC TP programs.

One TP program is produced per RAPID PROC without parameters. Each RAPID
statement becomes zero or more TP lines. A statement that cannot be converted
faithfully is never guessed: it becomes a '!TODO' remark in the program and an
entry in the conversion report, with its RAPID line number.

Mapping rules (see the report for the values actually used):
  MoveJ/MoveAbsJ -> J, MoveL -> L, MoveC -> C, target -> local P[n] with /POS data
  robtarget quaternion -> W,P,R        (robconv.geometry, fixed XYZ angles)
  confdata           -> CONFIG 'F/N U/D T/B, t1, t4, t6' (robconv.convert.configuration)
  speeddata          -> J: % of joint_speed_ref_mm_s ; L/C: mm/sec
  zonedata           -> FINE / CNT(radius_mm * cnt_per_mm, max 100)
  wobjdata / tooldata-> UFRAME_NUM / UTOOL_NUM, emitted when they change
  num / bool data    -> R[n] / F[n]      Set/Reset, SetDO -> DO[n]=ON/OFF
  IF/ELSEIF/ELSE     -> IF (...) THEN / ELSE / ENDIF (ELSEIF unrolled into nested IFs)
  FOR                -> FOR R[n]=a TO|DOWNTO b      WHILE -> LBL/JMP loop
  WaitTime           -> WAIT x(sec)      WaitDI/WaitDO/WaitUntil -> WAIT (cond)
  TPWrite "text"     -> MESSAGE[text]    TPErase -> (nothing)   SetGO / GInput -> GO[n]= / GI[n]
  PROC call          -> CALL NAME        Stop -> PAUSE   RETURN -> END   EXIT -> ABORT
"""

import math
import re
import unicodedata
from dataclasses import dataclass, field

from robconv.convert.config import ConversionConfig
from robconv.convert.configuration import UnsupportedConfdata, fanuc_config, fanuc_joints
from robconv.convert.values import Evaluator, Frame, JointTarget, RobTarget, Symbols, Unresolvable
from robconv.fanuc.tp import (
    Attributes,
    CartesianPosition,
    Instruction,
    JointPosition,
    Motion,
    Position,
    Program,
)
from robconv.rapid import nodes as n
from robconv.rapid.eio import Signal
from robconv.rapid.to_pseudo import format_expr
from robconv.rapid.walk import walk_statements

REMARK_MAX = 32  # characters after '!' shown on the pendant
MESSAGE_MAX = 24  # MESSAGE[...] text length (FANUC documentation; checked by the ROBOGUIDE message probe)
REGISTER_COMMENT_MAX = 16

_NEGATED = {"=": "<>", "<>": "=", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
_ARITHMETIC = {"+", "-", "*", "/", "DIV", "MOD"}
_SIGNAL_PREFIX = re.compile(r"^[dD][iIoO](?=[_0-9A-Z])")


class Untranslatable(Exception):
    """This RAPID construct has no faithful TP equivalent in the current scope."""


# ---------------------------------------------------------------------------
# Result objects (consumed by the CLI and the report)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Note:
    program: str  # TP program name ("" for global notes)
    rapid_line: int | None
    kind: str  # "TODO" (not converted) | "WARNING" (converted with an assumption)
    message: str


@dataclass(frozen=True, slots=True)
class PointInfo:
    number: int
    source: str  # RAPID expression
    rapid_line: int
    uf: int
    ut: int
    value: CartesianPosition | JointPosition


@dataclass(frozen=True, slots=True)
class ProgramInfo:
    program: Program
    module: str
    routine: str
    points: tuple[PointInfo, ...]


@dataclass(frozen=True, slots=True)
class Allocation:
    number: int
    rapid_name: str
    fixed: bool  # pinned by the mapping file
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FrameInfo:
    number: int
    rapid_name: str
    frame: Frame | None
    problem: str = ""


@dataclass
class ConversionResult:
    programs: list[ProgramInfo] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    registers: list[Allocation] = field(default_factory=list)
    flags: list[Allocation] = field(default_factory=list)
    digital_outputs: list[Allocation] = field(default_factory=list)
    digital_inputs: list[Allocation] = field(default_factory=list)
    group_outputs: list[Allocation] = field(default_factory=list)
    group_inputs: list[Allocation] = field(default_factory=list)
    uframes: list[FrameInfo] = field(default_factory=list)
    utools: list[FrameInfo] = field(default_factory=list)
    speeds: dict[tuple[str, str], str] = field(default_factory=dict)  # (RAPID speed, motion) -> TP
    zones: dict[str, str] = field(default_factory=dict)
    skipped_routines: list[tuple[str, str, str]] = field(default_factory=list)  # module, routine, reason

    @property
    def todo_count(self) -> int:
        return sum(1 for note in self.notes if note.kind == "TODO")


# ---------------------------------------------------------------------------
# Number allocation
# ---------------------------------------------------------------------------


class NumberTable:
    """RAPID name -> FANUC number: pinned by the user, else allocated in order of first use."""

    def __init__(self, fixed: dict[str, int], first: int) -> None:
        self.fixed = fixed
        self.first = first
        self.assigned: dict[str, Allocation] = {}

    def number(self, name: str, key: str | None = None, detail: str = "") -> int:
        key = (key or name).upper()
        if key in self.assigned:
            return self.assigned[key].number
        if key in self.fixed:
            number, fixed = self.fixed[key], True
        else:
            used = set(self.fixed.values()) | {a.number for a in self.assigned.values()}
            number, fixed = self.first, False
            while number in used:
                number += 1
        self.assigned[key] = Allocation(number, name, fixed, detail)
        return number

    def allocations(self) -> list[Allocation]:
        return sorted(self.assigned.values(), key=lambda a: a.number)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def ascii_text(text: str) -> str:
    """TP files are ASCII: strip accents, replace anything else."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return folded.replace('"', "'").replace(";", ",")


def remark_lines(text: str) -> list[str]:
    """A RAPID comment -> one or more TP remarks of at most 32 characters."""
    text = ascii_text(text).rstrip()
    if len(text) <= REMARK_MAX:
        return ["!" + text]
    chunks, current = [], ""
    for word in text.split(" "):
        while len(word) > REMARK_MAX:  # a single very long word, e.g. "!=========="
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:REMARK_MAX])
            word = word[REMARK_MAX:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) > REMARK_MAX:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return ["!" + c for c in chunks]


def tp_program_name(name: str, max_length: int) -> str:
    cleaned = re.sub(r"[^A-Z0-9_]", "_", ascii_text(name).upper())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = "P" + cleaned
    return cleaned[:max_length]


def round_half_up(value: float) -> int:
    """12.5 -> 13 as on a calculator (Python's round() gives 12: banker's rounding)."""
    return math.floor(value + 0.5)


def fmt_seconds(value: float) -> str:
    """Controller layout for WAIT times: width 6, 2 decimals, no leading zero ('   .30')."""
    text = f"{value:6.2f}"
    return text.replace(" 0.", "  .", 1) if abs(value) < 1 else text


def fmt_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _comment(name: str) -> str:
    return ascii_text(name)[:REGISTER_COMMENT_MAX].replace("]", ")")


# ---------------------------------------------------------------------------
# Converter (shared state across programs)
# ---------------------------------------------------------------------------


class Converter:
    def __init__(
        self,
        modules: list[n.Module],
        config: ConversionConfig | None = None,
        sources: dict[str, str] | None = None,
        signals: dict[str, Signal] | None = None,
    ) -> None:
        """`sources` (module name -> RAPID text) lets TODO entries quote the original line.
        `signals` (from EIO.cfg, upper-cased names) gives the real type of each I/O signal."""
        self.modules = modules
        self.config = config or ConversionConfig()
        self.eio = signals or {}
        self.source_lines = {name.upper(): text.splitlines() for name, text in (sources or {}).items()}
        self.symbols = Symbols.from_modules(modules)
        self.evaluator = Evaluator(self.symbols)
        cfg = self.config
        self.registers = NumberTable(cfg.registers, cfg.first_register)
        self.flags = NumberTable(cfg.flags, cfg.first_flag)
        self.douts = NumberTable(cfg.digital_outputs, cfg.first_digital_output)
        self.dins = NumberTable(cfg.digital_inputs, cfg.first_digital_input)
        self.gouts = NumberTable(cfg.group_outputs, cfg.first_group_output)
        self.gins = NumberTable(cfg.group_inputs, cfg.first_group_input)
        self.uframes = NumberTable(cfg.uframes, cfg.first_uframe)
        self.utools = NumberTable(cfg.utools, cfg.first_utool)
        self.frames: dict[tuple[str, int], FrameInfo] = {}
        self.written_registers: set[int] = set()  # assigned or used as FOR variable
        self.result = ConversionResult()
        self._warned: set[str] = set()
        self.do_names, self.di_names = self._signals_by_usage()
        self.program_names = self._program_names()

    # -- entry point -------------------------------------------------------

    def convert(self, routines: list[str] | None = None, program_modules: set[str] | None = None) -> ConversionResult:
        """`program_modules` (upper-case names): only their routines become programs, the other
        modules are data. Default: every module without the SYSMODULE attribute."""
        wanted = {r.upper() for r in routines} if routines else None
        for module in self.modules:
            if program_modules is not None:
                is_system = module.name.upper() not in program_modules
            else:
                is_system = "SYSMODULE" in module.attributes
            for routine in module.routines:
                if wanted is not None:
                    if routine.name.upper() not in wanted:
                        continue
                elif is_system:
                    continue  # system modules: data and utilities, converted only on request
                reason = self._skip_reason(routine)
                if reason:
                    self.result.skipped_routines.append((module.name, routine.name, reason))
                    continue
                translator = _RoutineTranslator(self, module, routine, self.program_names[routine.name.upper()])
                self.result.programs.append(translator.run())
        if wanted:
            found = {info.routine.upper() for info in self.result.programs}
            found |= {r.upper() for _, r, _ in self.result.skipped_routines}
            for missing in sorted(wanted - found):
                self.note("", None, "TODO", f"routine '{missing}' not found in the given modules")

        self._controller_comments()
        res = self.result
        res.registers = self.registers.allocations()
        res.flags = self.flags.allocations()
        res.digital_outputs = self.douts.allocations()
        res.digital_inputs = self.dins.allocations()
        res.group_outputs = self.gouts.allocations()
        res.group_inputs = self.gins.allocations()
        res.uframes = sorted((f for (k, _), f in self.frames.items() if k == "UF"), key=lambda f: f.number)
        res.utools = sorted((f for (k, _), f in self.frames.items() if k == "UT"), key=lambda f: f.number)
        return res

    @staticmethod
    def _skip_reason(routine: n.Routine) -> str:
        if routine.kind != "PROC":
            return f"{routine.kind} routines have no TP program equivalent"
        if routine.params:
            return "routine parameters are not converted (TP CALL arguments are untyped AR[n])"
        return ""

    def _program_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        used: set[str] = set()
        max_len = self.config.program_name_max_length
        for module in self.modules:
            for routine in module.routines:
                key = routine.name.upper()
                if key in names:
                    continue
                candidate = base = tp_program_name(routine.name, max_len)
                suffix = 1
                while candidate in used:
                    suffix += 1
                    candidate = f"{base[: max_len - len(str(suffix)) - 1]}_{suffix}"
                used.add(candidate)
                names[key] = candidate
        return names

    def _signals_by_usage(self) -> tuple[set[str], set[str]]:
        """Signal names whose direction is known from the instructions using them."""
        outputs: set[str] = set()
        inputs: set[str] = set()
        for module in self.modules:
            for routine in module.routines:
                for stmt in walk_statements(routine.body):
                    if isinstance(stmt, n.SetSignal) and isinstance(stmt.signal, n.Name):
                        outputs.add(stmt.signal.name.upper())
                    elif isinstance(stmt, n.ProcCall) and stmt.args and isinstance(stmt.args[0].value, n.Name):
                        name = stmt.args[0].value.name.upper()
                        if stmt.name.upper() in ("SETDO", "PULSEDO", "WAITDO"):
                            outputs.add(name)
                        elif stmt.name.upper() == "WAITDI":
                            inputs.add(name)
        return outputs, inputs

    # -- shared services -----------------------------------------------------

    def note(self, program: str, line: int | None, kind: str, message: str) -> None:
        self.result.notes.append(Note(program, line, kind, message))

    def warn_once(self, key: str, program: str, line: int | None, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.note(program, line, "WARNING", message)

    def frame_number(self, kind: str, expr: n.Expr | None, program: str, line: int) -> int:
        """UFRAME (kind "UF") or UTOOL ("UT") number for a wobj/tool argument."""
        if expr is None:
            expr = n.Name(n.Span(line, 0), "wobj0")
        if not isinstance(expr, n.Name):
            raise Untranslatable(f"{'work object' if kind == 'UF' else 'tool'} must be a named data: {format_expr(expr)}")
        table = self.uframes if kind == "UF" else self.utools
        number = table.number(expr.name)
        key = (kind, number)
        if key not in self.frames:
            try:
                frame = self.evaluator.wobj(expr) if kind == "UF" else self.evaluator.tool(expr)
                problem = ""
                if kind == "UF" and frame.robhold:
                    problem = "robot-held work object (stationary tool): not supported, frame values not usable"
                elif kind == "UT" and not frame.robhold:
                    problem = "stationary tool (robhold FALSE): not supported, frame values not usable"
            except Unresolvable as exc:
                frame, problem = None, str(exc)
            self.frames[key] = FrameInfo(number, expr.name, frame, problem)
        if self.frames[key].problem.startswith(("robot-held", "stationary")):
            raise Untranslatable(self.frames[key].problem)
        return number

    def _controller_comments(self) -> None:
        """Keep only the comments the controller keeps when it loads the program.

        Observed on ROBOGUIDE round trips: a register comment is stored only when
        the register is written (assignment, FOR); flag comments are never stored.
        Dropping the others makes the output identical to the controller's view.
        """
        def register(match: re.Match[str]) -> str:
            return match[0] if int(match[1]) in self.written_registers else f"R[{match[1]}]"

        for info in self.result.programs:
            lines = info.program.lines
            for i, line in enumerate(lines):
                if isinstance(line, Instruction) and not line.text.startswith("!"):
                    text = re.sub(r"R\[(\d+):[^\]]*\]", register, line.text)
                    lines[i] = Instruction(re.sub(r"F\[(\d+):[^\]]*\]", r"F[\1]", text))

    def written_register(self, name: str, key: str | None = None) -> str:
        text = self.register(name, key)
        self.written_registers.add(int(text[2 : text.index(":")]))
        return text

    def register(self, name: str, key: str | None = None) -> str:
        decl = self.symbols.get(name)
        detail = ""
        if decl is not None and decl.init is not None:
            detail = f"RAPID {decl.storage} initial value {format_expr(decl.init)}: set it on the controller"
        return f"R[{self.registers.number(name, key, detail)}:{_comment(name)}]"

    def flag(self, name: str) -> str:
        return f"F[{self.flags.number(name)}:{_comment(name)}]"

    def signal(self, expr: n.Expr, program: str, line: int) -> str | None:
        """'DI[n]' / 'DO[n]' if expr designates a digital signal, else None."""
        if isinstance(expr, n.FuncCall) and expr.name.upper() in ("DINPUT", "DOUTPUT") and len(expr.args) == 1:
            arg = expr.args[0].value
            if isinstance(arg, n.Name):
                table, prefix = (self.dins, "DI") if expr.name.upper() == "DINPUT" else (self.douts, "DO")
                return f"{prefix}[{table.number(arg.name)}]"
            return None
        if not isinstance(expr, n.Name) or self.symbols.get(expr.name) is not None:
            return None
        key = expr.name.upper()
        # Priority: mapping file, then EIO.cfg, then how the program uses it, then its name.
        if key in self.config.digital_inputs:
            return f"DI[{self.dins.number(expr.name)}]"
        if key in self.config.digital_outputs:
            return f"DO[{self.douts.number(expr.name)}]"
        if key in self.eio:
            sig = self.eio[key]
            detail = f"EIO.cfg: {sig.signal_type}, device {sig.device or '-'}, map {sig.device_map or '-'}"
            if sig.signal_type == "DI":
                return f"DI[{self.dins.number(expr.name, detail=detail)}]"
            if sig.signal_type == "DO":
                return f"DO[{self.douts.number(expr.name, detail=detail)}]"
            raise Untranslatable(f"'{expr.name}' is a {sig.signal_type} signal: group/analog I/O is not converted")
        if self.eio:
            self.warn_once(f"signal-eio:{key}", program, line, f"'{expr.name}' is not declared in EIO.cfg")
        if key in self.di_names:
            return f"DI[{self.dins.number(expr.name)}]"
        if key in self.do_names:
            return f"DO[{self.douts.number(expr.name)}]"
        match = _SIGNAL_PREFIX.match(expr.name)
        if match:
            is_input = match.group().upper() == "DI"
            self.warn_once(
                f"signal:{key}", program, line,
                f"'{expr.name}' assumed to be a digital {'input' if is_input else 'output'} from its name",
            )  # fmt: skip
            table, prefix = (self.dins, "DI") if is_input else (self.douts, "DO")
            return f"{prefix}[{table.number(expr.name)}]"
        return None


# ---------------------------------------------------------------------------
# One RAPID routine -> one TP program
# ---------------------------------------------------------------------------


class _RoutineTranslator:
    def __init__(self, conv: Converter, module: n.Module, routine: n.Routine, tp_name: str) -> None:
        self.c = conv
        self.module = module
        self.routine = routine
        self.name = tp_name
        self.lines: list[Instruction | Motion] = []
        self.positions: list[Position] = []
        self.points: list[PointInfo] = []
        self._point_keys: dict[tuple, int] = {}
        self.active_uf: int | None = None
        self.active_ut: int | None = None
        self.loop_vars: dict[str, str] = {}  # RAPID FOR variable -> register text
        self.next_label = 1

    def run(self) -> ProgramInfo:
        self.c.symbols.enter_routine(self.routine)
        for text in remark_lines(f"RAPID {self.module.name}.{self.routine.name}"):
            self.emit(text)
        self.block(self.routine.body)
        for handler in self.routine.handlers:
            self.todo(handler, handler.reason)
        attrs = Attributes(comment=ascii_text(self.routine.name)[:16], created=self.c.config.timestamp)
        program = Program(self.name, self.lines, self.positions, attrs)
        return ProgramInfo(program, self.module.name, self.routine.name, tuple(self.points))

    # -- output helpers --------------------------------------------------------

    def emit(self, text: str) -> None:
        self.lines.append(Instruction(text))

    def todo(self, stmt: n.Stmt, reason: str) -> None:
        line = stmt.span.line
        source = " ".join((stmt.raw if isinstance(stmt, n.Unsupported) else self.rapid_text(stmt)).split())
        self.emit("!" + ascii_text(f"TODO l.{line} {source.rstrip(';')}")[:REMARK_MAX])
        self.c.note(self.name, line, "TODO", f"{reason} — `{source[:80]}`")

    def rapid_text(self, stmt: n.Stmt) -> str:
        """The RAPID source line of a statement (comment stripped), or a re-print of it."""
        lines = self.c.source_lines.get(self.module.name.upper())
        if lines and 0 < stmt.span.line <= len(lines):
            text = lines[stmt.span.line - 1]
            if '"' not in text:
                text = text.split("!", 1)[0]
            return text.strip()
        return _source(stmt)

    def warn(self, stmt: n.Stmt, message: str) -> None:
        self.c.note(self.name, stmt.span.line, "WARNING", message)

    def label(self) -> int:
        number = self.next_label
        self.next_label += 1
        return number

    # -- statements -------------------------------------------------------------

    def block(self, stmts: tuple[n.Stmt, ...]) -> None:
        for stmt in stmts:
            checkpoint = len(self.lines)
            try:
                self.stmt(stmt)
            except (Untranslatable, Unresolvable) as exc:
                del self.lines[checkpoint:]  # drop a half-emitted construct
                self.todo(stmt, str(exc))

    def stmt(self, s: n.Stmt) -> None:
        match s:
            case n.Comment(text=text):
                for remark in remark_lines(text):
                    self.emit(remark)
            case n.DataDecl():
                self.local_decl(s)
            case n.Move():
                self.move(s)
            case n.SetSignal(signal=signal, value=value):
                self.emit(f"{self.output(signal, s)}={'ON' if value else 'OFF'}")
            case n.WaitTime(seconds=seconds, options=options):
                if options:
                    self.warn(s, f"WaitTime options ignored: {' '.join(a.name or '' for a in options)}")
                value = self.numeric(seconds)
                self.emit(f"WAIT {value}" if value.startswith("R[") else f"WAIT {fmt_seconds(float(value))}(sec)")
            case n.ProcCall():
                self.call(s)
            case n.Assign():
                self.assign(s)
            case n.If():
                self.if_stmt(s.branches, s.else_body)
            case n.For():
                self.for_stmt(s)
            case n.While():
                self.while_stmt(s)
            case n.Return(value=None):
                self.emit("END")
            case n.Exit():
                self.emit("ABORT")
            case n.Unsupported():
                self.todo(s, s.reason)
            case _:
                raise Untranslatable(f"{type(s).__name__} has no TP mapping")

    def local_decl(self, decl: n.DataDecl) -> None:
        # Positions and other data are resolved on use; num/bool locals become registers/flags.
        if decl.init is None or decl.dims:
            return
        if decl.type_name.lower() == "num":
            self.emit(f"{self.c.written_register(decl.name)}={self.numeric(decl.init)}")
        elif decl.type_name.lower() == "bool" and isinstance(decl.init, n.Bool):
            self.emit(f"{self.c.flag(decl.name)}=({'ON' if decl.init.value else 'OFF'})")

    # -- motion -------------------------------------------------------------------

    def move(self, m: n.Move) -> None:
        line = m.span.line
        # Resolve everything first: a failure must not leave a half-created point behind.
        uf = self.c.frame_number("UF", m.wobj, self.name, line)
        ut = self.c.frame_number("UT", m.tool, self.name, line)
        motion = "J" if m.kind in (n.MoveKind.J, n.MoveKind.ABSJ) else m.kind.value
        evaluator = self.c.evaluator
        to_value = evaluator.jointtarget(m.to_point) if m.kind is n.MoveKind.ABSJ else evaluator.robtarget(m.to_point)
        via_value = evaluator.robtarget(m.via_point) if m.via_point is not None else None
        if isinstance(to_value, JointTarget) and len(to_value.joints) < 6:
            raise Untranslatable(f"jointtarget with {len(to_value.joints)} axes")
        speed = self.speed(m.speed, motion)
        termination = self.termination(m.zone)
        ignored = [a.name for a in m.options if a.name and a.name.upper() != "NOEOFFS"]
        if ignored:
            self.warn(m, f"motion options ignored: {', '.join(ignored)}")

        via = self.point(m.via_point, via_value, uf, ut, line) if via_value is not None else None
        target = self.point(m.to_point, to_value, uf, ut, line)
        if uf != self.active_uf:
            self.emit(f"UFRAME_NUM={uf}")
            self.active_uf = uf
        if ut != self.active_ut:
            self.emit(f"UTOOL_NUM={ut}")
            self.active_ut = ut
        self.lines.append(Motion(motion, target, speed, termination, via))

    def point(self, expr: n.Expr, value: RobTarget | JointTarget, uf: int, ut: int, line: int) -> str:
        source = format_expr(expr)
        key = (source.upper(), uf, ut, type(value).__name__)
        if key in self._point_keys:
            return f"P[{self._point_keys[key]}]"
        number = len(self._point_keys) + 1
        self._point_keys[key] = number
        if isinstance(value, JointTarget):
            if self.c.config.joint_mapping:
                joints = fanuc_joints(value.joints)
                message = (
                    "joint targets (MoveAbsJ) converted with the measured axis conventions (J3 absolute, "
                    "J4/J5/J6 reversed, J6 +180): same posture, but the TCP lands elsewhere on another robot "
                    "model, check joint limits and clearances"
                )
            else:
                joints = tuple(value.joints[:6])
                message = "joint_mapping is off: joint targets (MoveAbsJ) copied axis by axis, re-teach them"
            tp_value: CartesianPosition | JointPosition = JointPosition(joints)
            self.c.warn_once("joint-targets", self.name, line, message)
        else:
            (x, y, z), (w, p, r) = value.pose.pos, value.pose.wpr()
            tp_value = CartesianPosition(x, y, z, w, p, r, self.config_string(value, line))
        self.positions.append(Position(number, uf, ut, tp_value))
        self.points.append(PointInfo(number, source, line, uf, ut, tp_value))
        return f"P[{number}]"

    def config_string(self, target: RobTarget, line: int) -> str:
        cfg = self.c.config
        if not cfg.config_mapping:
            self.c.warn_once(
                "config", self.name, line,
                f"config_mapping is off: every point uses CONFIG '{cfg.default_config}', check the arm posture",
            )  # fmt: skip
            return cfg.default_config
        try:
            text = fanuc_config(target.conf)
        except UnsupportedConfdata as exc:
            self.c.warn_once(f"confdata:{line}", self.name, line, f"{exc}: CONFIG '{cfg.default_config}' used")
            return cfg.default_config
        self.c.warn_once(
            "config-mapped", self.name, line,
            "CONFIG derived from ABB confdata (measured conventions, see docs). A different robot model can "
            "need a different posture to reach the same point, and the J6 turn number assumes the ABB tool "
            "frame is reused as UTOOL: check reachability in ROBOGUIDE",
        )  # fmt: skip
        return text

    def speed(self, expr: n.Expr, motion: str) -> str:
        speed = self.c.evaluator.speed(expr)
        cfg = self.c.config
        if motion == "J":
            percent = max(1, min(100, round_half_up(speed.v_tcp / cfg.joint_speed_ref_mm_s * 100)))
            text = f"{percent}%"
        else:
            text = f"{max(1, round_half_up(speed.v_tcp))}mm/sec"
        self.c.result.speeds[(speed.name, motion)] = text
        return text

    def termination(self, expr: n.Expr) -> str:
        zone = self.c.evaluator.zone(expr)
        if zone.fine:
            text = "FINE"
        else:
            text = f"CNT{max(0, min(100, round_half_up(zone.radius_mm * self.c.config.cnt_per_mm)))}"
        self.c.result.zones[zone.name] = text
        return text

    # -- I/O, calls, waits ------------------------------------------------------

    def output(self, expr: n.Expr, stmt: n.Stmt) -> str:
        ref = self.c.signal(expr, self.name, stmt.span.line)
        if ref is None or not ref.startswith("DO"):
            raise Untranslatable(f"'{format_expr(expr)}' is not a known digital output")
        return ref

    def call(self, call: n.ProcCall) -> None:
        name = call.name.upper()
        positional = [a.value for a in call.args if a.name is None]
        options = [a for a in call.args if a.name is not None]

        if name == "STOP":
            if call.args:
                options_text = " ".join(f"\\{a.name}" for a in call.args if a.name)
                self.c.warn_once(f"stop:{self.name}", self.name, call.span.line,
                                 f"Stop options ({options_text}) have no PAUSE equivalent and are ignored")  # fmt: skip
            self.emit("PAUSE")
        elif name == "SETDO" and len(positional) == 2 and not options:
            self.emit(f"{self.output(positional[0], call)}={self.on_off(positional[1])}")
        elif name in ("WAITDI", "WAITDO") and len(positional) == 2:
            if options:
                raise Untranslatable(f"{call.name} with {options[0].name} (timeout handling) is not converted")
            ref = self.c.signal(positional[0], self.name, call.span.line)
            if ref is None:
                raise Untranslatable(f"'{format_expr(positional[0])}' is not a known signal")
            self.emit(f"WAIT {ref}={self.on_off(positional[1])}")
        elif name == "WAITUNTIL" and len(positional) == 1:
            if options:
                raise Untranslatable(f"WaitUntil with {options[0].name} is not converted")
            self.emit(f"WAIT ({self.condition(positional[0])})")
        elif name == "TPERASE" and not call.args:
            pass  # the FANUC pendant has no user-screen clear: nothing to emit
        elif name == "TPWRITE" and len(positional) == 1:
            self.message(call, positional[0], options)
        elif name == "SETGO" and len(positional) == 2 and not options:
            self.emit(f"{self.group(positional[0], 'GO', call.span.line)}={self.numeric(positional[1])}")
        elif call.args:
            raise Untranslatable(f"call to {call.name} with arguments has no mapping")
        elif name in self.c.program_names:
            self.emit(f"CALL {self.c.program_names[name]}")
        else:
            raise Untranslatable(f"'{call.name}' is not a routine of the converted modules (system instruction?)")

    def message(self, call: n.ProcCall, text_expr: n.Expr, options: list[n.Arg]) -> None:
        """TPWrite with fixed text -> MESSAGE[...]. MESSAGE cannot show a variable value."""
        if options:
            raise Untranslatable(f"TPWrite \\{options[0].name}: MESSAGE cannot display a variable value")
        text = ascii_text(self.constant_string(text_expr)).replace("[", "(").replace("]", ")").strip()
        if not text:
            return
        if len(text) > MESSAGE_MAX:
            self.warn(call, f"TPWrite text cut to {MESSAGE_MAX} characters (FANUC MESSAGE limit): '{text}'")
            text = text[:MESSAGE_MAX].rstrip()
        self.emit(f"MESSAGE[{text}]")

    def constant_string(self, expr: n.Expr) -> str:
        match expr:
            case n.String(value=value):
                return value
            case n.BinaryOp(op="+", left=left, right=right):
                return self.constant_string(left) + self.constant_string(right)
            case n.Name(name=name):
                decl = self.c.symbols.get(name)
                if decl is not None and decl.storage == "CONST" and isinstance(decl.init, n.String):
                    return decl.init.value
        raise Untranslatable(f"text '{format_expr(expr)}' is built at run time: MESSAGE only shows fixed text")

    def group(self, expr: n.Expr, kind: str, line: int) -> str:
        """GO[n] / GI[n] for a group signal (kind 'GO' or 'GI', implied by the instruction)."""
        if not isinstance(expr, n.Name):
            raise Untranslatable(f"group signal must be a name: {format_expr(expr)}")
        key = expr.name.upper()
        fixed = self.c.config.group_outputs if kind == "GO" else self.c.config.group_inputs
        table = self.c.gouts if kind == "GO" else self.c.gins
        detail = ""
        if key not in fixed and key in self.c.eio:
            sig = self.c.eio[key]
            if sig.signal_type != kind:
                raise Untranslatable(f"'{expr.name}' is a {sig.signal_type} signal in EIO.cfg, not {kind}")
            detail = f"EIO.cfg: {kind}, device {sig.device or '-'}, map {sig.device_map or '-'}"
        elif key not in fixed and self.c.eio:
            self.c.warn_once(f"signal-eio:{key}", self.name, line, f"'{expr.name}' is not declared in EIO.cfg")
        return f"{kind}[{table.number(expr.name, detail=detail)}]"

    def on_off(self, expr: n.Expr) -> str:
        value = expr.value if isinstance(expr, n.Number | n.Bool) else None
        if value in (0, False):
            return "OFF"
        if value in (1, True):
            return "ON"
        raise Untranslatable(f"signal value must be 0 or 1, got {format_expr(expr)}")

    # -- data -----------------------------------------------------------------------

    def assign(self, a: n.Assign) -> None:
        if not isinstance(a.target, n.Name):
            raise Untranslatable("assignment to a record component or array element")
        type_name = self.c.symbols.type_of(a.target.name)
        if a.target.name.upper() in self.loop_vars:
            raise Untranslatable("assignment to a FOR loop variable")
        if type_name == "num":
            self.emit(f"{self.c.written_register(a.target.name)}={self.arithmetic(a.value)}")
        elif type_name == "bool" and isinstance(a.value, n.Bool):
            self.emit(f"{self.c.flag(a.target.name)}=({'ON' if a.value.value else 'OFF'})")
        else:
            raise Untranslatable(f"assignment of {type_name or 'undeclared data'} '{a.target.name}'")

    def arithmetic(self, expr: n.Expr) -> str:
        """Right-hand side of R[n]=...: a value or ONE arithmetic operation, as TP allows."""
        try:
            return fmt_number(self.c.evaluator.constant_number(expr))
        except Unresolvable:
            pass
        if isinstance(expr, n.BinaryOp) and expr.op in _ARITHMETIC:
            left, right = self.numeric(expr.left), self.numeric(expr.right)
            op = f" {expr.op} " if expr.op in ("DIV", "MOD") else expr.op
            return f"{left}{op}{right}"
        return self.numeric(expr)

    def numeric(self, expr: n.Expr) -> str:
        """A single TP numeric operand: a constant (CONST or literal), a register or a group input."""
        if isinstance(expr, n.FuncCall) and expr.name.upper() == "GINPUT" and len(expr.args) == 1 and expr.args[0].value:
            return self.group(expr.args[0].value, "GI", expr.span.line)
        if isinstance(expr, n.Name):
            key = expr.name.upper()
            if key in self.loop_vars:
                return self.loop_vars[key]
            decl = self.c.symbols.get(expr.name)
            if decl is not None and decl.type_name.lower() == "num" and decl.storage != "CONST":
                return self.c.register(expr.name)
        try:
            return fmt_number(self.c.evaluator.constant_number(expr))
        except Unresolvable as exc:
            raise Untranslatable(f"'{format_expr(expr)}' is not a simple numeric value ({exc})") from exc

    # -- control flow -----------------------------------------------------------------

    def if_stmt(self, branches: tuple[n.IfBranch, ...], else_body: tuple[n.Stmt, ...]) -> None:
        first, rest = branches[0], branches[1:]
        self.emit(f"IF ({self.condition(first.condition)}) THEN")
        self.block(first.body)
        if rest:  # ELSEIF -> ELSE + nested IF (TP has no ELSEIF)
            self.emit("ELSE")
            self.if_stmt(rest, else_body)
        elif else_body:
            self.emit("ELSE")
            self.block(else_body)
        self.emit("ENDIF")

    def for_stmt(self, loop: n.For) -> None:
        step = 1.0 if loop.step is None else self.c.evaluator.constant_number(loop.step)
        if step not in (1.0, -1.0):
            raise Untranslatable("FOR with a STEP other than 1 or -1 (TP FOR only counts by 1)")
        key = loop.var.upper()
        register = self.c.written_register(loop.var, key=f"{self.name}.{loop.var}")
        start, end = self.numeric(loop.start), self.numeric(loop.end)
        self.emit(f"FOR {register}={start} {'TO' if step > 0 else 'DOWNTO'} {end}")
        self.loop_vars[key] = register
        try:
            self.block(loop.body)
        finally:
            del self.loop_vars[key]
        self.emit("ENDFOR")

    def while_stmt(self, loop: n.While) -> None:
        top = self.label()
        if isinstance(loop.condition, n.Bool) and loop.condition.value:
            self.emit(f"LBL[{top}]")
            self.block(loop.body)
            self.emit(f"JMP LBL[{top}]")
            return
        exit_label = self.label()
        self.emit(f"LBL[{top}]")
        self.emit(f"IF ({self.condition(loop.condition, negate=True)}) THEN")
        self.emit(f"JMP LBL[{exit_label}]")
        self.emit("ENDIF")
        self.block(loop.body)
        self.emit(f"JMP LBL[{top}]")
        self.emit(f"LBL[{exit_label}]")

    # -- conditions (TP mixed logic) --------------------------------------------------

    def condition(self, expr: n.Expr, negate: bool = False) -> str:
        """RAPID boolean expression -> TP mixed-logic condition, without outer parentheses.

        Negation is pushed down (De Morgan, inverted comparisons) so the output
        never needs the '!' operator.
        """
        match expr:
            case n.UnaryOp(op="NOT", operand=operand):
                return self.condition(operand, not negate)
            case n.BinaryOp(op="AND" | "OR", left=left, right=right):
                op = expr.op if not negate else ("OR" if expr.op == "AND" else "AND")
                parts = []
                for side in (left, right):
                    text = self.condition(side, negate)
                    if isinstance(side, n.BinaryOp) and side.op in ("AND", "OR"):
                        text = f"({text})"
                    parts.append(text)
                return f"{parts[0]} {op} {parts[1]}"
            case n.BinaryOp(op=op, left=left, right=right) if op in _NEGATED:
                op = _NEGATED[op] if negate else op
                signal = self.c.signal(left, self.name, expr.span.line)
                if signal is not None:
                    if op not in ("=", "<>"):
                        raise Untranslatable(f"signal compared with '{op}'")
                    state = self.on_off(right)
                    if op == "<>":
                        state = "OFF" if state == "ON" else "ON"
                    return f"{signal}={state}"
                return f"{self.numeric(left)}{op}{self.numeric(right)}"
            case n.Name(name=name) if self.c.symbols.type_of(name) == "bool":
                return f"{self.c.flag(name)}={'OFF' if negate else 'ON'}"
            case n.Name() | n.FuncCall():
                signal = self.c.signal(expr, self.name, expr.span.line)
                if signal is not None:
                    return f"{signal}={'OFF' if negate else 'ON'}"
        raise Untranslatable(f"condition not convertible: {format_expr(expr)}")


def _source(stmt: n.Stmt) -> str:
    """Short RAPID text of a statement, for TODO remarks and the report."""
    from robconv.rapid.to_pseudo import _Printer

    printer = _Printer()
    printer.stmt(stmt, 0)
    return printer.lines[0].split("| ", 1)[1].strip() if printer.lines else type(stmt).__name__


def convert(
    modules: list[n.Module],
    config: ConversionConfig | None = None,
    routines: list[str] | None = None,
    sources: dict[str, str] | None = None,
    signals: dict[str, Signal] | None = None,
    program_modules: set[str] | None = None,
) -> ConversionResult:
    return Converter(modules, config, sources, signals).convert(routines, program_modules)

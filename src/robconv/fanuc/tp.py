"""In-memory model of a FANUC TP program, independent of the .LS text layout.

Instructions are stored as already-formatted TP text (e.g. "DO[1]=ON",
"UFRAME_NUM=1"): TP has no nested expression grammar worth modelling, and
keeping the text makes the writer trivial to check against real exports.
Motion lines are structured because their layout differs (see ls_writer).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Instruction:
    text: str  # "" for an empty line


@dataclass(frozen=True, slots=True)
class Motion:
    """J/L/C motion. For C, `via` is the circle point, `target` the end point."""

    kind: str  # "J" | "L" | "C"
    target: str  # "P[3]" or "PR[1:Home]"
    speed: str  # "50%" | "500mm/sec"
    termination: str  # "FINE" | "CNT50"
    via: str | None = None


Line = Instruction | Motion


@dataclass(frozen=True, slots=True)
class CartesianPosition:
    x: float
    y: float
    z: float
    w: float
    p: float
    r: float
    config: str = "N U T, 0, 0, 0"


@dataclass(frozen=True, slots=True)
class JointPosition:
    joints: tuple[float, ...]  # degrees, J1..J6


@dataclass(frozen=True, slots=True)
class Position:
    """One entry of the /POS section: P[number] for motion group 1."""

    number: int
    uf: int
    ut: int
    value: CartesianPosition | JointPosition


@dataclass(slots=True)
class Attributes:
    """/ATTR block. Defaults are those of a program created with the editor.

    PROG_SIZE / MEMORY_SIZE are recomputed by the controller on load; 0 is what
    offline generators commonly write.
    """

    comment: str = ""
    owner: str = "MNEDITOR"
    created: datetime = field(default_factory=lambda: datetime(2000, 1, 1))
    modified: datetime | None = None  # None: same as created
    prog_size: int = 0
    memory_size: int = 0
    protect: str = "READ_WRITE"
    file_name: str = ""
    default_group: str = "1,*,*,*,*"
    local_registers: str | None = None  # "0,0,0" on recent controllers; absent on R-J3i exports
    appl: tuple[str, ...] = ()  # raw /APPL lines, e.g. "  SPOT : TRUE ;"


@dataclass(slots=True)
class Program:
    name: str
    lines: list[Line] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    attributes: Attributes = field(default_factory=Attributes)
    macro: bool = False

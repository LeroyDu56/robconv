"""FANUC TP program model -> ASCII .LS text.

Layout sources (details in docs/fanuc_ls_format.md):

  CONFIRMED on real exports (R-J3i backups):
    /PROG, /ATTR (tabs), /APPL, /MN, /POS, /END; CRLF line endings;
    "%4d:  instr ;" for instructions, "%4d:J P[1] 100% FINE    ;" for motions
    (motion letter right after the colon), "%4d:   ;" for an empty line;
    joint /POS block (UF/UT line then J1..J6 on two lines).

  From FANUC documentation / public exports, NOT yet confirmed on this
  project's files — validate by loading into ROBOGUIDE:
    cartesian /POS block (CONFIG + X Y Z / W P R), two-line circular motion.
"""

from datetime import datetime

from robconv.fanuc.tp import Attributes, CartesianPosition, JointPosition, Motion, Program

CRLF = "\r\n"


def write_ls(program: Program) -> str:
    lines = _header(program.name, program.macro, program.attributes, len(program.lines))
    lines.append("/MN")
    for number, line in enumerate(program.lines, start=1):
        if isinstance(line, Motion):
            lines += _motion(number, line)
        else:
            lines.append(f"{number:4d}:  {line.text} ;" if line.text else f"{number:4d}:   ;")
    lines.append("/POS")
    for pos in program.positions:
        lines += _position(pos.number, pos.uf, pos.ut, pos.value)
    lines.append("/END")
    return CRLF.join(lines) + CRLF


def _date(value: datetime) -> str:
    return value.strftime("DATE %y-%m-%d  TIME %H:%M:%S")


def _header(name: str, macro: bool, attrs: Attributes, line_count: int) -> list[str]:
    modified = attrs.modified or attrs.created
    lines = [
        f"/PROG  {name}" + ("\t\tMacro" if macro else ""),
        "/ATTR",
        f"OWNER\t\t= {attrs.owner};",
        f'COMMENT\t\t= "{attrs.comment}";',
        f"PROG_SIZE\t= {attrs.prog_size};",
        f"CREATE\t\t= {_date(attrs.created)};",
        f"MODIFIED\t= {_date(modified)};",
        f"FILE_NAME\t= {attrs.file_name};",
        "VERSION\t\t= 0;",
        f"LINE_COUNT\t= {line_count};",
        f"MEMORY_SIZE\t= {attrs.memory_size};",
        f"PROTECT\t\t= {attrs.protect};",
        "TCD:  STACK_SIZE\t= 0,",
        "      TASK_PRIORITY\t= 50,",
        "      TIME_SLICE\t= 0,",
        "      BUSY_LAMP_OFF\t= 0,",
        "      ABORT_REQUEST\t= 0,",
        "      PAUSE_REQUEST\t= 0;",
        f"DEFAULT_GROUP\t= {attrs.default_group};",
        "CONTROL_CODE\t= 00000000 00000000;",
    ]
    if attrs.appl:
        lines.append("/APPL")
        lines += attrs.appl
    return lines


def _motion(number: int, m: Motion) -> list[str]:
    tail = f"{m.speed} {m.termination}    ;"
    if m.kind == "C":
        if m.via is None:
            raise ValueError("circular motion needs a via point")
        # Documented layout: the end point goes on a continuation line without a number.
        return [f"{number:4d}:C {m.via}    ", f"    :  {m.target} {tail}"]
    return [f"{number:4d}:{m.kind} {m.target} {tail}"]


def _position(number: int, uf: int, ut: int, value: CartesianPosition | JointPosition) -> list[str]:
    lines = [f"P[{number}]{{", "   GP1:"]
    if isinstance(value, JointPosition):
        j = [f"J{i}={v:10.3f} deg" for i, v in enumerate(value.joints, start=1)]
        lines += [
            f"\tUF : {uf}, UT : {ut},\t",
            "\t" + ",\t".join(j[:3]) + ",",
            "\t" + ",\t".join(j[3:]),
        ]
    else:
        v = value
        lines += [
            f"\tUF : {uf}, UT : {ut},\t\tCONFIG : '{v.config}',",
            f"\tX = {v.x:9.3f}  mm,\tY = {v.y:9.3f}  mm,\tZ = {v.z:9.3f}  mm,",
            f"\tW = {v.w:9.3f} deg,\tP = {v.p:9.3f} deg,\tR = {v.r:9.3f} deg",
        ]
    lines.append("};")
    return lines


__all__ = ["CRLF", "write_ls"]

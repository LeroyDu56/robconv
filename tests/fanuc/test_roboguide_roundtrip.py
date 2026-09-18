"""Round trip through a real FANUC controller (ROBOGUIDE).

tests/fixtures/fanuc/<case>/*.LS (robconv output) were loaded into
ROBOGUIDE, compiled to TP by the virtual controller and exported back to .LS:
tests/fixtures/fanuc/roboguide_export/. The controller accepted every program,
so every construct robconv emits there is valid TP.

This test regenerates the programs and requires them to match the controller's
own export byte for byte. Only the header values the controller computes on
load are taken from the export: sizes, dates, comment padding, LOCAL_REGISTERS.
The exports predate confdata -> CONFIG, the MoveAbsJ joint mapping and TPWrite values shown
as text: the settings of that time are used here.
"""

import re
from dataclasses import replace
from datetime import datetime

import pytest
from helpers import FIXTURES

from robconv.convert import ConversionConfig, convert
from robconv.fanuc.ls_writer import write_ls
from robconv.fanuc.tp import Attributes, CartesianPosition, Instruction, Motion, Position, Program
from robconv.rapid import parse_file

EXPORTS = sorted((FIXTURES / "fanuc" / "roboguide_export").glob("*.LS"))


def controller_header(text: str) -> dict[str, str]:
    header = text.split("/MN\r\n", 1)[0]
    return {m[1]: m[2] for m in re.finditer(r"^(\w+)\t+= (.*?);?\r$", header, re.MULTILINE)}


CASES = ["pick_and_place", "logic_and_io", "hmi_and_groups"]


def generated_programs():
    programs = {}
    for case in CASES:
        parsed = parse_file(FIXTURES / "rapid" / f"{case}.mod")
        result = convert([parsed.module], ConversionConfig(timestamp=datetime(2026, 1, 1), config_mapping=False, joint_mapping=False,
                                          tpwrite_values="todo"),
                         sources={parsed.module.name: parsed.text})  # fmt: skip
        programs |= {info.program.name: info.program for info in result.programs}
    return programs


@pytest.mark.parametrize("export", EXPORTS, ids=lambda p: p.name)
def test_generated_program_matches_controller_export(export):
    real = export.read_bytes().decode("ascii")
    header = controller_header(real)
    program = generated_programs()[export.stem]

    def date(key: str) -> datetime:
        return datetime.strptime(header[key], "DATE %y-%m-%d  TIME %H:%M:%S")

    program.attributes = replace(
        program.attributes,
        comment=header["COMMENT"].strip('"'),
        prog_size=int(header["PROG_SIZE"]),
        memory_size=int(header["MEMORY_SIZE"]),
        created=date("CREATE"),
        modified=date("MODIFIED"),
        local_registers=header.get("LOCAL_REGISTERS"),
    )
    assert write_ls(program) == real


def test_every_generated_program_was_validated():
    assert sorted(generated_programs()) == sorted(p.stem for p in EXPORTS)


def _controller_number(text: str) -> float:
    """'-.000' / '.000' are tiny non-zero values the controller rounded: keep them non-zero."""
    value = float(text)
    if value == 0 and text.strip() != "0.000":
        return -1e-9 if text.strip().startswith("-") else 1e-9
    return value


def test_cartesian_positions_computed_by_the_controller_are_reproduced():
    """CFGPROBE: joint points converted to cartesian by ROBOGUIDE (CONFIG, WPR, number layout)."""
    real = (FIXTURES / "probes" / "results" / "CFGPROBE_roboguide.LS").read_bytes().decode("ascii")
    header = controller_header(real)
    block = re.compile(
        r"P\[(\d+)\]\{\r\n   GP1:\r\n\tUF : (\d+), UT : (\d+),\t\tCONFIG : '([^']*)',\r\n"
        r"\tX = (.{9})  mm,\tY = (.{9})  mm,\tZ = (.{9})  mm,\r\n"
        r"\tW = (.{9}) deg,\tP = (.{9}) deg,\tR = (.{9}) deg\r\n\};"
    )
    positions = [
        Position(int(m[1]), int(m[2]), int(m[3]),
                 CartesianPosition(*(_controller_number(m[i]) for i in range(5, 11)), config=m[4]))
        for m in block.finditer(real)
    ]  # fmt: skip
    assert len(positions) == 16
    motions = [Motion("J", f"P[{p.number}]", "10%", "FINE") for p in positions]
    program = Program(
        "CFGPROBE",
        [Instruction("!robconv CONFIG probe"), *motions],
        positions,
        Attributes(
            comment=header["COMMENT"].strip('"'),
            prog_size=int(header["PROG_SIZE"]),
            memory_size=int(header["MEMORY_SIZE"]),
            created=datetime.strptime(header["CREATE"], "DATE %y-%m-%d  TIME %H:%M:%S"),
            modified=datetime.strptime(header["MODIFIED"], "DATE %y-%m-%d  TIME %H:%M:%S"),
            local_registers=header.get("LOCAL_REGISTERS"),
        ),
    )
    assert write_ls(program) == real


def test_controller_cuts_messages_at_the_limit_robconv_uses():
    """MESSAGE[...] of 24, 25, 32 and 40 characters were loaded into ROBOGUIDE: all accepted,
    every text silently cut to 24 characters on export. robconv cuts at the same length (with a warning)."""
    from robconv.convert.translate import MESSAGE_MAX

    probes = FIXTURES / "probes" / "message_length"
    for sent in sorted((probes / "sent").glob("MSG*.LS")):
        exported = (probes / "roboguide" / sent.name).read_bytes().decode("ascii")
        sent_text = re.search(r"MESSAGE\[([^\]]*)\]", sent.read_bytes().decode("ascii"))[1]
        kept_text = re.search(r"MESSAGE\[([^\]]*)\]", exported)[1]
        assert kept_text == sent_text[:MESSAGE_MAX], sent.name
    assert MESSAGE_MAX == 24

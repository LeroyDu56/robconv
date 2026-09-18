"""Round trip through a real FANUC controller (ROBOGUIDE).

tests/fixtures/fanuc/pick_and_place/*.LS (robconv output) were loaded into
ROBOGUIDE, compiled to TP by the virtual controller and exported back to .LS:
tests/fixtures/fanuc/roboguide_export/. The controller accepted every program,
so every construct robconv emits there is valid TP.

This test regenerates the programs and requires them to match the controller's
own export byte for byte. Only the header values the controller computes on
load are taken from the export: sizes, dates, comment padding, LOCAL_REGISTERS.
"""

import re
from dataclasses import replace
from datetime import datetime

import pytest
from helpers import FIXTURES

from robconv.convert import ConversionConfig, convert
from robconv.fanuc.ls_writer import write_ls
from robconv.rapid import parse_file

EXPORTS = sorted((FIXTURES / "fanuc" / "roboguide_export").glob("*.LS"))


def controller_header(text: str) -> dict[str, str]:
    header = text.split("/MN\r\n", 1)[0]
    return {m[1]: m[2] for m in re.finditer(r"^(\w+)\t+= (.*?);?\r$", header, re.MULTILINE)}


def generated_programs():
    parsed = parse_file(FIXTURES / "rapid" / "pick_and_place.mod")
    result = convert([parsed.module], ConversionConfig(timestamp=datetime(2026, 1, 1)),
                     sources={parsed.module.name: parsed.text})  # fmt: skip
    return {info.program.name: info.program for info in result.programs}


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

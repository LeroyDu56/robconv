"""Writer vs real FANUC exports (client-confidential, never committed).

Scans $ROBCONV_PRIVATE_FANUC (default ./fanuc, git-ignored) for .LS exports
made only of joint motions with a filled /POS section, rebuilds each program
from its own content and checks that the writer reproduces the file byte for
byte. No value from the private files is written in this repository. Skipped
when the corpus is absent, e.g. on CI.
"""

import os
import re
from datetime import datetime
from pathlib import Path

import pytest

from robconv.fanuc.ls_writer import write_ls
from robconv.fanuc.tp import Attributes, JointPosition, Motion, Position, Program

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = Path(os.environ.get("ROBCONV_PRIVATE_FANUC", _REPO_ROOT / "fanuc"))

_MOTION = re.compile(r"^\s*\d+:([JL]) (P\[\d+\]) (\S+) (\S+)\s+;$")
_POS_HEAD = re.compile(r"P\[(\d+)\]\{\r\n   GP1:\r\n\tUF : (\d+), UT : (\d+),\t\r\n")
_JOINT = re.compile(r"J\d=\s*(-?\d+\.\d+) deg")


def _joint_exports() -> list[Path]:
    if not _CORPUS.is_dir():
        return []
    found = []
    for path in sorted(p for p in _CORPUS.rglob("*") if p.suffix.lower() == ".ls"):
        text = path.read_bytes().decode("ascii", errors="replace")
        body = text.split("/MN\r\n", 1)[-1].split("/POS", 1)[0].splitlines()
        if "J1=" in text and body and all(_MOTION.match(line) for line in body):
            found.append(path)
    return found


EXPORTS = _joint_exports()


def _rebuild(real: str) -> Program:
    lines = real.split("\r\n")
    header = {k.strip(): v.strip(" \t=;") for k, v in (line.split("\t", 1) for line in lines[2:12] if "\t" in line)}

    def date(key: str) -> datetime:
        return datetime.strptime(header[key], "DATE %y-%m-%d  TIME %H:%M:%S")

    appl: tuple[str, ...] = ()
    if "/APPL\r\n" in real:
        appl = tuple(real.split("/APPL\r\n", 1)[1].split("\r\n/MN", 1)[0].split("\r\n"))
    attributes = Attributes(
        comment=header["COMMENT"].strip('"'),
        owner=header["OWNER"],
        created=date("CREATE"),
        modified=date("MODIFIED"),
        prog_size=int(header["PROG_SIZE"]),
        memory_size=int(header["MEMORY_SIZE"]),
        protect=header["PROTECT"],
        appl=appl,
    )
    mn = real.split("/MN\r\n", 1)[1].split("/POS", 1)[0].splitlines()
    motions = [Motion(*_MOTION.match(line).groups()) for line in mn]  # type: ignore[union-attr]
    positions = []
    pos_text = real.split("/POS\r\n", 1)[1]
    for block in pos_text.split("};\r\n")[:-1]:
        head = _POS_HEAD.search(block)
        joints = tuple(float(v) for v in _JOINT.findall(block))
        positions.append(Position(int(head[1]), int(head[2]), int(head[3]), JointPosition(joints)))  # type: ignore[index]
    return Program(lines[0].split()[1], motions, positions, attributes)


@pytest.mark.skipif(not EXPORTS, reason="no private FANUC joint-motion export available")
@pytest.mark.parametrize("path", EXPORTS, ids=lambda p: p.name)
def test_writer_reproduces_real_export_byte_for_byte(path):
    real = path.read_bytes().decode("ascii")
    assert write_ls(_rebuild(real)) == real

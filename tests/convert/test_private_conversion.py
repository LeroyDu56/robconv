"""Convert the private RAPID corpus end to end (client-confidential, never committed).

Asserts robustness only: every routine is either converted or reported, the
writer produces pure ASCII, and every point referenced in /MN exists in /POS.
Skipped when no corpus is present.
"""

import re

import pytest
from rapid.test_private_corpus import FILES

from robconv.convert import ConversionConfig, build_report, convert
from robconv.fanuc.ls_writer import write_ls
from robconv.fanuc.tp import Motion
from robconv.rapid import parse_file


@pytest.mark.skipif(not FILES, reason="no private RAPID corpus (set ROBCONV_PRIVATE_CORPUS)")
def test_private_corpus_converts():
    parsed = [parse_file(path) for path in FILES]
    modules = [p.module for p in parsed]
    result = convert(modules, ConversionConfig(), sources={p.module.name: p.text for p in parsed})
    assert result.programs

    for info in result.programs:
        text = write_ls(info.program)
        text.encode("ascii")
        numbers = {pos.number for pos in info.program.positions}
        for line in info.program.lines:
            if isinstance(line, Motion):
                for ref in filter(None, (line.target, line.via)):
                    assert int(re.search(r"\d+", ref)[0]) in numbers, (info.program.name, ref)
    build_report(result, ConversionConfig(), [p.name for p in FILES])

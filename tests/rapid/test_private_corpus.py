"""Robustness test over real controller backups, which are client-confidential.

The corpus is never committed. Point ROBCONV_PRIVATE_CORPUS at a folder of
RAPID files (searched recursively); by default ./abb is used when present
(it is git-ignored). Without a corpus, these tests are skipped — as on CI.

Only robustness is asserted (no crash, no syntax error): expected outputs of
private files must not be written into the repository.
"""

import os
from pathlib import Path

import pytest

from robconv.cli import iter_rapid_files
from robconv.rapid import parse_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = Path(os.environ.get("ROBCONV_PRIVATE_CORPUS", _REPO_ROOT / "abb"))
FILES = list(iter_rapid_files([_CORPUS])) if _CORPUS.is_dir() else []


@pytest.mark.skipif(not FILES, reason="no private RAPID corpus (set ROBCONV_PRIVATE_CORPUS)")
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_real_file_parses_without_errors(path):
    result = parse_file(path)
    assert result.module is not None
    assert result.ok, "\n".join(str(d) for d in result.diagnostics)

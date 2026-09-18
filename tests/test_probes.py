"""The committed configuration probes must match tools/make_config_probes.py."""

import sys
from pathlib import Path

from helpers import FIXTURES, parse_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import make_config_probes

PROBES = FIXTURES / "probes"


def test_fanuc_probe_is_up_to_date():
    assert (PROBES / "CFGPROBE.LS").read_bytes().decode("ascii") == make_config_probes.fanuc_probe()


def test_abb_probe_is_up_to_date_and_parses():
    text = (PROBES / "CfgProbe.mod").read_bytes().decode("ascii")
    assert text == make_config_probes.abb_probe()
    module = parse_module(text)
    (table,) = module.declarations
    assert len(table.init.items) == len(make_config_probes.JOINT_SETS)

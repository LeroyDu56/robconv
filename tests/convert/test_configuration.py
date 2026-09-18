"""confdata -> CONFIG, checked against measurements from both controllers.

tests/fixtures/probes/results/ holds, for the same 16 joint sets:
  cfgprobe_robotstudio.txt  ABB confdata, TCP position and orientation (CalcRobT, IRB 6700)
  CFGPROBE_roboguide.LS     FANUC CONFIG, position and W,P,R computed by ROBOGUIDE
"""

import math
import random
import re
import sys
from pathlib import Path

import pytest
from helpers import FIXTURES

from robconv.convert.configuration import UnsupportedConfdata, fanuc_config
from robconv.geometry import mat_mul, quat_to_matrix, rot_x, rot_y, rot_z, wpr_to_matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from make_config_probes import JOINT_SETS

RESULTS = FIXTURES / "probes" / "results"
JOINTS = [joints for _, joints in JOINT_SETS]


def load_abb() -> dict[int, dict]:
    points: dict[int, dict] = {}
    for line in (RESULTS / "cfgprobe_robotstudio.txt").read_text().splitlines():
        index, kind, *rest = line.split()
        entry = points.setdefault(int(index), {})
        if kind == "trans":
            entry["trans"] = tuple(map(float, rest))
        elif kind == "rot":
            entry["rot"] = quat_to_matrix(tuple(map(float, rest)))
        else:
            entry["conf"] = tuple(int(v) for v in kind.strip("[]").split(","))
    return points


def load_fanuc() -> dict[int, dict]:
    text = (RESULTS / "CFGPROBE_roboguide.LS").read_text().split("/POS")[1]
    pattern = re.compile(
        r"P\[(\d+)\]\{.*?CONFIG : '([^']*)',\s*X =\s*(\S+)  mm,.*?"
        r"W =\s*(\S+) deg,\s*P =\s*(\S+) deg,\s*R =\s*(\S+) deg",
        re.DOTALL,
    )
    return {
        int(m[1]): {"config": m[2], "x": float(m[3]), "rot": wpr_to_matrix(*map(float, m.groups()[3:]))}
        for m in pattern.finditer(text)
    }


ABB, FANUC = load_abb(), load_fanuc()


def fanuc_turn(angle: float) -> int:
    """Turn t such that angle is in (-180 + 360t, 180 + 360t]."""
    return math.ceil((angle - 180) / 360)


def fanuc_config_from_joints(j: tuple[float, ...], elbow: str = "U", side: str = "T") -> str:
    """FANUC rules measured on ROBOGUIDE (letters U/D and T/B passed in: they depend on geometry)."""
    flip = "F" if j[4] > 0 else "N"
    return f"{flip} {elbow} {side}, {fanuc_turn(j[0])}, {fanuc_turn(j[3])}, {fanuc_turn(j[5])}"


def abb_conf_from_joints(j: tuple[float, ...], cfx_high_bits: int = 0) -> tuple[int, int, int, int]:
    """ABB rules measured on RobotStudio: quadrants of axes 1, 4, 6; cfx bit 0 = axis 5 negative."""
    return (math.floor(j[0] / 90), math.floor(j[3] / 90), math.floor(j[5] / 90), cfx_high_bits | (j[4] < 0))


def abb_to_fanuc_joints(j: tuple[float, ...]) -> tuple[float, ...]:
    """Same physical posture: FANUC J3 is absolute (forearm pitch = -(J2 + J3) ABB), wrist axes
    reversed, flange frames 180 deg apart about z. J2 does not change the orientation: kept as is."""
    return (j[0], j[1], -(j[1] + j[2]), -j[3], -j[4], 180 - j[5])


def assert_matrix_close(a, b, tol):
    for row_a, row_b in zip(a, b, strict=True):
        assert row_a == pytest.approx(row_b, abs=tol)


# ---------------------------------------------------------------------------
# 1. Each controller's own convention, checked on its own measurements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(1, 17))
def test_abb_confdata_rules(index):
    j = JOINTS[index - 1]
    measured = ABB[index]["conf"]
    behind_axis_1 = ABB[index]["trans"][0] < 0 if j[0] == 0 else None
    assert measured[:3] == abb_conf_from_joints(j)[:3]
    assert measured[3] & 1 == (j[4] < 0)
    if behind_axis_1 is not None:
        assert bool(measured[3] & 4) == behind_axis_1


@pytest.mark.parametrize("index", range(1, 17))
def test_fanuc_config_rules(index):
    j = JOINTS[index - 1]
    letters = FANUC[index]["config"].split(",")[0].split()
    expected = fanuc_config_from_joints(j, elbow=letters[1], side=letters[2])
    assert FANUC[index]["config"] == expected
    if j[0] == 0:
        assert (letters[2] == "B") == (FANUC[index]["x"] < 0)


# ---------------------------------------------------------------------------
# 2. Orientation models fitted on the measurements (axis directions)
# ---------------------------------------------------------------------------


def abb_orientation(j, r0):
    return mat_mul(mat_mul(rot_z(j[0]), mat_mul(rot_y(j[1] + j[2]), mat_mul(rot_x(j[3]), rot_y(j[4])))),
                   mat_mul(r0, rot_z(j[5])))  # fmt: skip


def fanuc_orientation(j, r0):
    return mat_mul(mat_mul(rot_z(j[0]), mat_mul(rot_y(-j[2]), mat_mul(rot_x(-j[3]), rot_y(-j[4])))),
                   mat_mul(r0, rot_z(-j[5])))  # fmt: skip


def base_orientation(model, measured_point_1):
    """Flange orientation at all-zero joints, from point 1 (only J5 = -90)."""
    m = model(JOINTS[0], ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    return mat_mul(tuple(zip(*m)), measured_point_1)


R0_ABB = base_orientation(abb_orientation, ABB[1]["rot"])
R0_FANUC = base_orientation(fanuc_orientation, FANUC[1]["rot"])


@pytest.mark.parametrize("index", range(1, 17))
def test_orientation_models_reproduce_both_controllers(index):
    j = JOINTS[index - 1]
    assert_matrix_close(abb_orientation(j, R0_ABB), ABB[index]["rot"], tol=2e-6)  # 6 printed decimals
    assert_matrix_close(fanuc_orientation(j, R0_FANUC), FANUC[index]["rot"], tol=1e-5)


def test_flange_frames_differ_by_half_turn_about_z():
    assert_matrix_close(R0_FANUC, mat_mul(R0_ABB, rot_z(180)), tol=2e-6)


def test_equivalent_joints_give_the_same_flange_orientation():
    rng = random.Random(7)
    for _ in range(200):
        j = tuple(rng.uniform(-170, 170) for _ in range(6))
        assert_matrix_close(fanuc_orientation(abb_to_fanuc_joints(j), R0_FANUC), abb_orientation(j, R0_ABB), 1e-6)


# ---------------------------------------------------------------------------
# 3. The mapping itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", [1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16])  # J2 = J3 = 0: elbow up, front
def test_mapping_on_measured_abb_points(index):
    j = JOINTS[index - 1]
    assert fanuc_config(ABB[index]["conf"]) == fanuc_config_from_joints(abb_to_fanuc_joints(j))


def test_mapping_on_random_postures():
    rng = random.Random(2026)
    for _ in range(5000):
        j = (rng.uniform(-179, 179), 0, 0, rng.uniform(-400, 400), rng.uniform(-120, 120), rng.uniform(-400, 400))
        if any(abs(a % 90) < 1e-6 for a in (j[0], j[3], j[5])):  # exact quadrant boundary: undefined
            continue
        high = rng.choice((0, 2, 4, 6))
        elbow, side = ("D" if high & 2 else "U"), ("B" if high & 4 else "T")
        expected = fanuc_config_from_joints(abb_to_fanuc_joints(j), elbow, side)
        assert fanuc_config(abb_conf_from_joints(j, high)) == expected, j


@pytest.mark.parametrize(
    ("conf", "expected"),
    [
        ((0, 0, 0, 0), "N U T, 0, 0, 0"),  # typical taught point, tool down
        ((0, 0, 0, 1), "F U T, 0, 0, 0"),
        ((0, 0, 0, 7), "F D B, 0, 0, 0"),
        ((0, -1, 2, 0), "N U T, 0, 0, 0"),
        ((0, 0, -1, 0), "N U T, 0, 0, 1"),  # ABB J6 slightly negative -> FANUC J6 just above 180
        ((2, 2, 3, 0), "N U T, 1, -1, 0"),
    ],
)
def test_mapping_examples(conf, expected):
    assert fanuc_config(conf) == expected


def test_non_six_axis_confdata_is_rejected():
    with pytest.raises(UnsupportedConfdata):
        fanuc_config((0, 0, 0, 8))

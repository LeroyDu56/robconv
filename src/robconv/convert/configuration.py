"""ABB confdata -> FANUC CONFIG string.

Both conventions were MEASURED, not assumed: the same 16 joint sets were
evaluated by RobotStudio (CalcRobT, IRB 6700) and ROBOGUIDE (joint -> cartesian
conversion), see tools/make_config_probes.py and tests/fixtures/probes/results/.
Fitting the measured orientations gives, for axes at the same physical posture:

    J1_fanuc = J1_abb
    J4_fanuc = -J4_abb          (axis direction reversed)
    J5_fanuc = -J5_abb          (axis direction reversed)
    J6_fanuc = 180 - J6_abb     (reversed, and the flange frames differ by 180 deg
                                 about z when the ABB tframe is reused as UTOOL)

ABB confdata [cf1, cf4, cf6, cfx]: cf1/cf4/cf6 are the quadrants of axes 1, 4, 6
(quadrant q = angle in [q*90, q*90 + 90)); cfx for a 6-axis arm is
    bit 0: axis 5 negative          bit 1: wrist centre behind the lower arm
    bit 2: wrist centre behind axis 1
FANUC CONFIG 'F/N U/D T/B, t1, t4, t6':
    F when J5 > 0; D elbow down; B wrist behind axis 1; turn numbers of J1, J4, J6
    (turn t = angle in (-180 + 360t, 180 + 360t]).

Quadrant boundaries (multiples of 90) fall on turn boundaries (odd multiples
of 180), so each ABB quadrant maps to exactly one FANUC turn number.
"""


class UnsupportedConfdata(ValueError):
    """confdata outside the 6-axis serial-arm convention (e.g. 7-axis or parallel robots)."""


def fanuc_config(conf: tuple[int, int, int, int]) -> str:
    cf1, cf4, cf6, cfx = conf
    if not 0 <= cfx <= 7:
        raise UnsupportedConfdata(f"cfx={cfx} is not a 6-axis arm configuration (expected 0-7)")
    flip = "F" if cfx & 1 else "N"  # ABB axis 5 negative == FANUC J5 positive
    elbow = "D" if cfx & 2 else "U"
    side = "B" if cfx & 4 else "T"
    # FANUC angle ranges per ABB quadrant: J1 same, J4 = -angle, J6 = 180 - angle.
    turn_j1 = (cf1 + 2) // 4
    turn_j4 = (1 - cf4) // 4
    turn_j6 = (3 - cf6) // 4
    return f"{flip} {elbow} {side}, {turn_j1}, {turn_j4}, {turn_j6}"

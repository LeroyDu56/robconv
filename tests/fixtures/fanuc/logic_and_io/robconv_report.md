# robconv conversion report

- Generated: 2026-01-01 08:00:00 by robconv 0.1.0
- Sources: `logic_and_io.mod`
- Programs: 2, items to review: 0 TODO, 4 warnings

> The `.LS` files are text listings to load and check in ROBOGUIDE (or convert on the controller).
> They are **not** directly executable: frames, registers, I/O numbers and every TODO below
> must be reviewed by the integrator before running on a robot.

## Programs

| TP program | RAPID routine | Lines | Points | TODO |
|---|---|---|---|---|
| `PALLETIZE.LS` | LogicAndIo.Palletize | 31 | 3 | 0 |
| `COUNTDOWN.LS` | LogicAndIo.CountDown | 13 | 0 | 0 |

## Frames to set up on the controller

Values are the RAPID frames converted to FANUC X, Y, Z (mm) and W, P, R (deg).
User frames are `uframe x oframe` of the work object, relative to the robot world frame.

### User frames (UFRAME)

| UF | RAPID wobjdata | X, Y, Z | W, P, R | Problem |
|---|---|---|---|---|
| 0 | wobj0 | 0.000, 0.000, 0.000 | 0.000, 0.000, 0.000 |  |
| 1 | wobjStack | 800.000, -200.000, 0.000 | 0.000, 0.000, 0.000 |  |

### Tool frames (UTOOL)

| UT | RAPID tooldata | X, Y, Z | W, P, R | Problem |
|---|---|---|---|---|
| 1 | tool0 | 0.000, 0.000, 0.000 | 0.000, 0.000, 0.000 |  |
| 2 | tSuction | 0.000, 0.000, 120.000 | 0.000, 0.000, 0.000 |  |

## Registers, flags and I/O

Automatic numbers start at 1: pin them with a mapping file (`--map`) to avoid clashing with registers and I/O already used on the controller.

| TP | RAPID name | Number from | Note |
|---|---|---|---|
| R[1] | nParts | automatic | RAPID PERS initial value 0: set it on the controller |
| R[2] | nRow | automatic | RAPID VAR initial value 0: set it on the controller |
| R[3] | nCol | automatic | RAPID VAR initial value 0: set it on the controller |
| R[4] | tSettle | automatic | RAPID PERS initial value 0.4: set it on the controller |
| R[5] | k | automatic |  |
| R[6] | nLayer | automatic | RAPID PERS initial value 0: set it on the controller |
| F[1] | bStackFull | automatic |  |
| DO[1] | doRowStart | automatic |  |
| DO[2] | doVacuum | automatic |  |
| DI[1] | diStackReady | automatic |  |
| DI[2] | diForceRow | automatic |  |
| DI[3] | diAbort | automatic |  |

## Speed and zone mapping

- Joint moves: `%` = RAPID TCP speed / 2000 mm/s (`joint_speed_ref_mm_s`), clamped to 1-100 %. There is no exact equivalent: tune on the robot.
- Zones: `CNT` = zone radius (mm) x 1 (`cnt_per_mm`), max 100. RAPID zones are distances, FANUC CNT is a percentage: approximate.

| RAPID speed | Motion | TP |
|---|---|---|
| v1000 | J | 50% |
| v200 | L | 200mm/sec |
| v500 | L | 500mm/sec |
| v800 | J | 40% |

| RAPID zone | TP |
|---|---|
| fine | FINE |
| z20 | CNT20 |
| z50 | CNT50 |

## Points

### PALLETIZE

| P | RAPID target | RAPID line | UF/UT | Value |
|---|---|---|---|---|
| P[1] | `jSafe` | 24 | 0/1 | J 0.000 -20.000 20.000 0.000 70.000 0.000 |
| P[2] | `Offs(pStack, 0, 0, 150)` | 34 | 1/2 | X 500.000 Y -300.000 Z 550.000 W 180.000 P 0.000 R 90.000 |
| P[3] | `pStack` | 35 | 1/2 | X 500.000 Y -300.000 Z 400.000 W 180.000 P 0.000 R 90.000 |

## Items to review

| Program | RAPID line | Kind | Detail |
|---|---|---|---|
| COUNTDOWN | 52 | WARNING | 'diAbort' assumed to be a digital input from its name |
| PALLETIZE | 24 | WARNING | joint targets (MoveAbsJ) are copied axis by axis: ABB and FANUC axis zero positions and J2/J3 conventions differ, re-teach these points |
| PALLETIZE | 29 | WARNING | 'diForceRow' assumed to be a digital input from its name |
| PALLETIZE | 34 | WARNING | CONFIG derived from ABB confdata (measured conventions, see docs). A different robot model can need a different posture to reach the same point, and the J6 turn number assumes the ABB tool frame is reused as UTOOL: check reachability in ROBOGUIDE |

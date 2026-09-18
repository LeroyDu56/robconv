# robconv conversion report

- Generated: 2026-01-01 08:00:00 by robconv 0.2.0
- Sources: `pick_and_place.mod`
- Programs: 3, items to review: 8 TODO, 4 warnings

> The `.LS` files are text listings to load and check in ROBOGUIDE (or convert on the controller).
> They are **not** directly executable: frames, registers, I/O numbers and every TODO below
> must be reviewed by the integrator before running on a robot.

## Programs

| TP program | RAPID routine | Lines | Points | TODO |
|---|---|---|---|---|
| `MAIN.LS` | PickAndPlace.main | 16 | 2 | 0 |
| `PICK.LS` | PickAndPlace.Pick | 9 | 2 | 0 |
| `PLACE.LS` | PickAndPlace.Place | 20 | 2 | 8 |

### Routines not converted

| RAPID routine | Reason |
|---|---|
| PickAndPlace.IsFixtureFull | FUNC routines have no TP program equivalent |

## Frames to set up on the controller

Values are the RAPID frames converted to FANUC X, Y, Z (mm) and W, P, R (deg).
User frames are `uframe x oframe` of the work object, relative to the robot world frame.

### User frames (UFRAME)

| UF | RAPID wobjdata | X, Y, Z | W, P, R | Problem |
|---|---|---|---|---|
| 0 | wobj0 | 0.000, 0.000, 0.000 | 0.000, 0.000, 0.000 |  |
| 1 | wobjFixture | 1250.000, -400.000, 720.000 | 0.000, 0.000, 90.000 |  |

### Tool frames (UTOOL)

| UT | RAPID tooldata | X, Y, Z | W, P, R | Problem |
|---|---|---|---|---|
| 1 | tool0 | 0.000, 0.000, 0.000 | 0.000, 0.000, 0.000 |  |
| 2 | tGripper | 0.000, 0.000, 185.500 | 0.000, 0.000, 0.000 |  |

## Registers, flags and I/O

Automatic numbers start at 1: pin them with a mapping file (`--map`) to avoid clashing with registers and I/O already used on the controller.

| TP | RAPID name | Number from | Note |
|---|---|---|---|
| R[1] | i | automatic |  |
| R[2] | nSlot | automatic | RAPID VAR initial value 0: set it on the controller |
| R[3] | nCycles | automatic | RAPID PERS initial value 0: set it on the controller |
| DO[1] | DO_GripperClose | automatic |  |
| DI[1] | DI_PartReady | automatic |  |

## Speed and zone mapping

- Joint moves: `%` = RAPID TCP speed / 2000 mm/s (`joint_speed_ref_mm_s`), clamped to 1-100 %. There is no exact equivalent: tune on the robot.
- Zones: `CNT` = zone radius (mm) x 1 (`cnt_per_mm`), max 100. RAPID zones are distances, FANUC CNT is a percentage: approximate.

| RAPID speed | Motion | TP |
|---|---|---|
| v1000 | J | 50% |
| v200 | L | 200mm/sec |
| v300 | C | 300mm/sec |
| v500 | L | 500mm/sec |

| RAPID zone | TP |
|---|---|
| fine | FINE |
| z10 | CNT10 |
| z20 | CNT20 |
| z50 | CNT50 |

## Points

### MAIN

| P | RAPID target | RAPID line | UF/UT | Value |
|---|---|---|---|---|
| P[1] | `jParking` | 32 | 0/1 | J 0.000 -30.000 -0.000 -0.000 -90.000 180.000 |
| P[2] | `pHome` | 33 | 0/2 | X 600.000 Y 0.000 Z 900.000 W 180.000 P 0.000 R 180.000 |

### PICK

| P | RAPID target | RAPID line | UF/UT | Value |
|---|---|---|---|---|
| P[1] | `Offs(pPick, 0, 0, 100)` | 46 | 0/2 | X 812.350 Y -245.100 Z 405.000 W -179.293 P 0.000 R -90.000 |
| P[2] | `pPick` | 47 | 0/2 | X 812.350 Y -245.100 Z 305.000 W -179.293 P 0.000 R -90.000 |

### PLACE

| P | RAPID target | RAPID line | UF/UT | Value |
|---|---|---|---|---|
| P[1] | `pArcMid` | 59 | 1/2 | X 900.000 Y 0.000 Z 500.000 W 180.000 P 0.000 R 180.000 |
| P[2] | `pArcEnd` | 59 | 1/2 | X 950.000 Y 100.000 Z 450.000 W 180.000 P 0.000 R 180.000 |

## Items to review

| Program | RAPID line | Kind | Detail |
|---|---|---|---|
| MAIN | 32 | WARNING | joint targets (MoveAbsJ) converted with the measured axis conventions (J3 absolute, J4/J5/J6 reversed, J6 +180): same posture, but the TCP lands elsewhere on another robot model, check joint limits and clearances |
| MAIN | 33 | WARNING | CONFIG derived from ABB confdata (measured conventions, see docs). A different robot model can need a different posture to reach the same point, and the J6 turn number assumes the ABB tool frame is reused as UTOOL: check reachability in ROBOGUIDE |
| MAIN | 35 | WARNING | 'DI_PartReady' assumed to be a digital input from its name |
| PLACE | 54 | TODO | assignment of robtarget 'pPlace' — `pPlace:=Offs(pHome,nOffsets{nSlot},0,-400);` |
| PLACE | 55 | TODO | assignment to a record component or array element — `pPlace.trans.z:=pPlace.trans.z+2.5;` |
| PLACE | 57 | TODO | 'pPlace' has no initial value (set at run time) — `MoveJ pPlace,v800,z20,tGripper\WObj:=wobjFixture;` |
| PLACE | 61 | TODO | 'pPlace' has no initial value (set at run time) — `MoveL pPlace,v300,fine,tGripper\WObj:=wobjFixture;` |
| PLACE | 64 | WARNING | WaitTime options ignored: InPos |
| PLACE | 65 | TODO | GOTO is not supported — `GOTO skip_log;` |
| PLACE | 66 | TODO | call to TPWrite with arguments has no V2 mapping — `TPWrite "Placed in slot "\Num:=nSlot;` |
| PLACE | 67 | TODO | labels (GOTO targets) are not supported — `skip_log:` |
| PLACE | 68 | TODO | ERROR handlers are not supported — `ERROR IF ERRNO=ERR_WAIT_MAXTIME RETRY; RAISE;` |

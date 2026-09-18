# robconv conversion report

- Generated: 2026-01-01 08:00:00 by robconv 0.2.0
- Sources: `hmi_and_groups.mod`
- Programs: 1, items to review: 0 TODO, 0 warnings

> The `.LS` files are text listings to load and check in ROBOGUIDE (or convert on the controller).
> They are **not** directly executable: frames, registers, I/O numbers and every TODO below
> must be reviewed by the integrator before running on a robot.

## Programs

| TP program | RAPID routine | Lines | Points | TODO |
|---|---|---|---|---|
| `REPORTCYCLE.LS` | HmiAndGroups.ReportCycle | 8 | 0 | 0 |

## Frames to set up on the controller

Values are the RAPID frames converted to FANUC X, Y, Z (mm) and W, P, R (deg).
User frames are `uframe x oframe` of the work object, relative to the robot world frame.

### User frames (UFRAME)

_None._

### Tool frames (UTOOL)

_None._

## Registers, flags and I/O

Automatic numbers start at 1: pin them with a mapping file (`--map`) to avoid clashing with registers and I/O already used on the controller.

| TP | RAPID name | Number from | Note |
|---|---|---|---|
| R[1] | nCode | automatic | RAPID VAR initial value 0: set it on the controller |
| GO[1] | goEchoCode | automatic |  |
| GO[2] | goStatus | automatic |  |
| GI[1] | giCycleCode | automatic |  |

## Speed and zone mapping

- Joint moves: `%` = RAPID TCP speed / 2000 mm/s (`joint_speed_ref_mm_s`), clamped to 1-100 %. There is no exact equivalent: tune on the robot.
- Zones: `CNT` = zone radius (mm) x 1 (`cnt_per_mm`), max 100. RAPID zones are distances, FANUC CNT is a percentage: approximate.

_None._

_None._

## Points

## Items to review

_None._

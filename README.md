# robconv

Cross-brand industrial robot program converter, starting with **ABB RAPID → FANUC TP**.

robconv reads RAPID modules, converts each routine into a FANUC `.LS` program, and writes a
**conversion report**. The report lists the frames, registers and I/O the programs expect, the
heuristics applied, and every RAPID line that still needs manual work.

> **The output is a starting point for commissioning, not a program to run blind.** `.LS` files are
> text listings to load and check in ROBOGUIDE (or on the controller). Anything robconv cannot
> convert faithfully becomes a `!TODO` remark plus a report entry. It is never guessed.

Pure Python, **no runtime dependency**. Tested against real controller backups (not published):
- **ABB side:** RobotWare 7, ~10,000 lines in 24 modules, parsed with zero syntax errors, 365 moves converted.
- **FANUC side:** the writer reproduces a real R-J3i export **byte for byte**.

## Quick start

```bash
pip install -e ".[dev]"

robconv convert tests/fixtures/rapid/pick_and_place.mod -o out/     # .LS files + robconv_report.md
robconv convert backup/RAPID -o out/ --map mapping.json --routine main
robconv parse   tests/fixtures/rapid/pick_and_place.mod              # RAPID AST as a readable listing
robconv stats   backup/RAPID                                          # parser coverage report
```

RAPID in, from [tests/fixtures/rapid/pick_and_place.mod](tests/fixtures/rapid/pick_and_place.mod):

```
PROC Pick()
    ! approach, grip, retract
    MoveJ Offs(pPick,0,0,100),v1000,z20,tGripper;
    MoveL pPick,v200,fine,tGripper;
    Set DO_GripperClose;
    WaitTime 0.3;
    MoveL Offs(pPick,0,0,100),v500,z10,tGripper;
ENDPROC
```

FANUC out, from [tests/fixtures/fanuc/pick_and_place/PICK.LS](tests/fixtures/fanuc/pick_and_place/PICK.LS):

```
/MN
   1:  !RAPID PickAndPlace.Pick ;
   2:  ! approach, grip, retract ;
   3:  UFRAME_NUM=0 ;
   4:  UTOOL_NUM=2 ;
   5:J P[1] 50% CNT20    ;
   6:L P[2] 200mm/sec FINE    ;
   7:  DO[1]=ON ;
   8:  WAIT 0.30(sec) ;
   9:L P[1] 500mm/sec CNT10    ;
/POS
P[1]{
   GP1:
	UF : 0, UT : 2,		CONFIG : 'N U T, 0, 0, 0',
	X =   812.350  mm,	Y =  -245.100  mm,	Z =   405.000  mm,
	W =  -179.293 deg,	P =     0.000 deg,	R =   -90.000 deg
};
...
```

The matching report is [robconv_report.md](tests/fixtures/fanuc/pick_and_place/robconv_report.md).

## What is converted

| RAPID | FANUC TP | Notes |
|---|---|---|
| `MoveJ` / `MoveL` / `MoveC` / `MoveAbsJ` | `J` / `L` / `C` / `J` + local `P[n]` | Targets resolved at conversion time, including `Offs()` and `RelTool()` |
| robtarget quaternion | W, P, R | Fixed-axis XYZ angles, property-tested on thousands of random rotations |
| `wobjdata` / `tooldata` | `UFRAME_NUM` / `UTOOL_NUM` | Frame values (X Y Z W P R) listed in the report |
| `speeddata` | `%` (joint) / `mm/sec` | Joint %: heuristic, configurable |
| `zonedata` | `FINE` / `CNTn` | Radius → CNT: heuristic, configurable |
| `num` / `bool` data | `R[n:name]` / `F[n:name]` | |
| `Set` / `Reset` / `SetDO` | `DO[n]=ON/OFF` | |
| `WaitTime`, `WaitDI/DO`, `WaitUntil` | `WAIT` | |
| `IF / ELSEIF / ELSE` | `IF (...) THEN / ELSE / ENDIF` | `ELSEIF` unrolled, negations pushed down |
| `FOR` (step ±1), `WHILE` | `FOR R[n]=a TO/DOWNTO b`, `LBL`/`JMP` loop | |
| routine call, `Stop`, `RETURN`, `EXIT` | `CALL`, `PAUSE`, `END`, `ABORT` | |
| comments | `!remark` | Split to 32 characters, accents folded to ASCII |

**Reported as TODO**:
- calls with arguments, parameterised routines, `FUNC`, `TRAP`;
- targets computed at run time;
- error handlers, `RECORD`, `GOTO`, late binding.

The format status of every emitted construct is in [docs/fanuc_ls_format.md](docs/fanuc_ls_format.md).

### Mapping file

Register, I/O and frame numbers are allocated automatically in order of first use. Pin them to
match the target cell:

```json
{
  "registers": {"nCycles": 10},
  "digital_outputs": {"DO_GripperClose": 3},
  "uframes": {"wobjFixture": 2},
  "utools": {"tGripper": 1},
  "joint_speed_ref_mm_s": 2000,
  "program_name_max_length": 8
}
```

## Layout

```
src/robconv/
  cli.py                 robconv parse / stats / convert
  geometry.py            quaternion <-> matrix <-> W,P,R, Offs, RelTool
  rapid/                 V1: RAPID lexer, parser, AST, JSON/pseudo-code output
  convert/               V2: data evaluation, RAPID -> TP translation, report
  fanuc/                 V2: TP program model, .LS writer
tests/
  rapid/ convert/ fanuc/ unit, golden and private-corpus tests
  fixtures/rapid/        synthetic RAPID sources
  fixtures/fanuc/        expected conversion output (.LS + report)
docs/                    design notes, RAPID grammar, .LS format status
```

## Tests

```bash
pytest                                             # unit + golden tests
ROBCONV_PRIVATE_CORPUS=/path/to/rapid ROBCONV_PRIVATE_FANUC=/path/to/fanuc pytest
                                                   # + real backups (never committed)
ROBCONV_UPDATE_GOLDEN=1 pytest                     # regenerate expected outputs, then review the diff
```

## Roadmap

- Validate the documented `.LS` constructs (cartesian `/POS`, circular motion) on a ROBOGUIDE import.
- `CALL` with arguments (`AR[n]`), `TEST/CASE` → `SELECT`, `TPWrite` → `MESSAGE`.
- ABB `confdata` → FANUC `CONFIG` for a given pair of robot models.

## License

MIT — see [LICENSE](LICENSE).

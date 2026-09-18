# FANUC `.LS` output: what is confirmed and what is not

robconv writes ASCII `.LS` listings. Every construct it emits is listed here with its
source of truth. Two sources confirm a construct:

* **Real export**: observed on real R-J3i controller backups (26 `.LS` files, private).
  For a joint-motion program, the writer reproduces the real file **byte for byte**
  (`tests/fanuc/test_private_ls.py`, run against the private corpus).
* **ROBOGUIDE round trip**: the generated programs
  [`tests/fixtures/fanuc/pick_and_place/`](../tests/fixtures/fanuc/pick_and_place/) were loaded into
  ROBOGUIDE, compiled to TP by the virtual controller without error, and exported back:
  [`tests/fixtures/fanuc/roboguide_export/`](../tests/fixtures/fanuc/roboguide_export/). robconv
  reproduces that export byte for byte. The only exception is the header values the controller
  computes itself (`tests/fanuc/test_roboguide_roundtrip.py`).

Every construct robconv emits has now been validated on a controller.

## File structure

| Element | Emitted as | Status |
|---|---|---|
| Sections | `/PROG`, `/ATTR` (tab-aligned keys), optional `/APPL`, `/MN`, `/POS`, `/END` | Real export + ROBOGUIDE |
| Line endings | CRLF | Real export + ROBOGUIDE |
| `PROG_SIZE`, `MEMORY_SIZE`, dates | `0` and conversion time. The controller recomputes them on load | ROBOGUIDE (accepted) |
| `COMMENT` | Routine name, not padded. Recent controllers pad it to 16 on export | ROBOGUIDE (accepted) |
| `LOCAL_REGISTERS` | Not emitted by default. Recent controllers add `0,0,0` on export | ROBOGUIDE (accepted without it) |
| Instruction line | `   1:  UFRAME_NUM=0 ;` | Real export + ROBOGUIDE |
| Padded terminator | `CALL PLACE    ;`, `R[3:nCycles]=R[3:nCycles]+1    ;`, `WAIT DI[1]=ON    ;`, `WAIT (...)    ;` | Real export + ROBOGUIDE |
| Numbers in `/POS` | 3 decimals, no leading zero below 1 (`.500`, `-.000`), exact zero `0.000` | ROBOGUIDE |
| Register / flag comments | `R[n:name]` kept only for registers the programs write; flags never commented (the controller keeps comments in its own tables) | ROBOGUIDE |
| Motion line | `   5:J P[1] 50% CNT20    ;` (motion letter right after `:`) | Real export + ROBOGUIDE |
| Empty line | `   6:   ;` | Real export |
| Empty program | `/MN` immediately followed by `/POS` | Real export |

## Instructions

| TP | Example | Status |
|---|---|---|
| Joint / linear motion | `J P[1] 50% CNT50`, `L P[2] 500mm/sec FINE` | ROBOGUIDE |
| Circular motion | `C P[1]` + continuation line `    :  P[2] 300mm/sec CNT10    ;` | ROBOGUIDE |
| Frames | `UFRAME_NUM=1`, `UTOOL_NUM=2` | Real export + ROBOGUIDE |
| Digital output | `DO[1]=ON` | Real export + ROBOGUIDE |
| Register | `R[2:nSlot]=R[1:i]`, `R[3:nCycles]=R[3:nCycles]+1` | ROBOGUIDE |
| Register with `DIV` / `MOD` | `R[2:nRow]=R[1] DIV 4` | ROBOGUIDE |
| Flag | `F[1]=(ON)` | Real export + ROBOGUIDE |
| Remark | `!text` (no parentheses in `.LS`) | Real export + ROBOGUIDE |
| Label / jump | `LBL[1]`, `JMP LBL[1]` | Real export + ROBOGUIDE |
| Call | `CALL PICK` | Real export + ROBOGUIDE |
| Mixed-logic IF block, nested | `IF (R[2:nSlot]=1) THEN` / `ELSE` / `ENDIF` | ROBOGUIDE |
| Conditions with `AND` / `OR`, flags | `IF (R[1]>=12 OR F[1]=ON) THEN` | ROBOGUIDE |
| FOR loop | `FOR R[1:i]=1 TO 3` / `ENDFOR` | ROBOGUIDE |
| FOR loop, descending | `FOR R[5:k]=3 DOWNTO 1` | ROBOGUIDE |
| Timed wait | `WAIT    .30(sec)` (width 6, no leading zero) | ROBOGUIDE |
| Other waits | `WAIT R[4]`, `WAIT DI[1]=ON`, `WAIT DO[2]=ON`, `WAIT (DI[1]=OFF OR R[6]<>0)` | ROBOGUIDE |
| Pause / abort | `PAUSE`, `ABORT` | Real export + ROBOGUIDE |
| End | `END` | ROBOGUIDE |

## `/POS` section

Both layouts are confirmed byte for byte.

Joint position (real export):

```
P[1]{
   GP1:
	UF : 0, UT : 1,	
	J1=     0.000 deg,	J2=   -30.000 deg,	J3=    30.000 deg,
	J4=     0.000 deg,	J5=    90.000 deg,	J6=     0.000 deg
};
```

Cartesian position (ROBOGUIDE round trip):

```
P[1]{
   GP1:
	UF : 1, UT : 2,		CONFIG : 'N U T, 0, 0, 0',
	X =   900.000  mm,	Y =     0.000  mm,	Z =   500.000  mm,
	W =   180.000 deg,	P =     0.000 deg,	R =   180.000 deg
};
```

## Known limits

* The arm configuration (`CONFIG`) is derived from ABB `confdata` with conventions **measured** on
  both controllers: the same 16 joint sets were evaluated by RobotStudio (IRB 6700-140/2.85) and ROBOGUIDE
  (M-20iD/25).
  See `src/robconv/convert/configuration.py` and `tests/convert/test_configuration.py`. The
  measurements show that FANUC J4, J5, J6 turn opposite to ABB, that FANUC J3 is absolute
  (J2/J3 coupling), and that the flange frames differ by 180° about z. Two limits remain. A
  different robot model may need another posture to reach a point. The J6 turn number assumes
  the ABB tool frame is reused as UTOOL. The `U/D` and `T/B` letters are the same geometric criteria on
  both brands: wrist centre past the shoulder–elbow line, and wrist centre behind axis 1. This was
  checked on every probe point, including a J3 sweep showing that the ABB bit flips exactly at the
  IRB 6700 elbow singularity (J3 = −81.83°). `"config_mapping": false` in the mapping file
  falls back to `'N U T, 0, 0, 0'`.
* Joint targets (`MoveAbsJ`) are converted for the same posture:
  `(J1, J2, -(J2+J3), -J4, -J5, 180-J6)`. J2's direction was confirmed by fitting the arm
  geometry on the measured positions: the fit is exact and recovers the M-20iD/25 link lengths.
  On another robot model the TCP lands elsewhere, so check joint limits and clearances.
  `"joint_mapping": false` copies the values as they are.
* No `P[n]` comment is emitted (`P[1:HOME]`). The report maps every `P[n]` back to its RAPID name.

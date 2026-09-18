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

* The arm configuration is not transferred yet. Every point uses `'N U T, 0, 0, 0'` and a warning is
  raised. The FANUC convention is now measured (`tests/fixtures/probes/results/`): `F` when J5 > 0,
  turn numbers for J1, J4, J6 in that order, `B` when the wrist is behind axis 1. The ABB side
  is being measured with the same joint sets.
* Joint targets (`MoveAbsJ`) are copied axis by axis. Axis zero positions and the J2/J3
  convention differ between the brands, so these points must be re-taught.
* No `P[n]` comment is emitted (`P[1:HOME]`). The report maps every `P[n]` back to its RAPID name.

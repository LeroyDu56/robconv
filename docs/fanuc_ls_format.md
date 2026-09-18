# FANUC `.LS` output: what is confirmed and what is not

robconv writes ASCII `.LS` listings. Every construct it emits is listed here with
its source of truth. **Confirmed** means observed on real controller exports
(R-J3i backups, 26 `.LS` files) and, for the joint program, reproduced **byte for byte**
by the writer (`tests/fanuc/test_private_ls.py`, run against the private corpus).
**Documented** means taken from FANUC documentation or public exports, but
not yet seen in this project's files. Load the output in ROBOGUIDE to validate these.

## File structure

| Element | Emitted as | Status |
|---|---|---|
| Header | `/PROG`, `/ATTR` (tab-aligned keys), optional `/APPL`, `/MN`, `/POS`, `/END` | Confirmed |
| Line endings | CRLF | Confirmed (most exports; one LF-only file also seen) |
| `PROG_SIZE`, `MEMORY_SIZE` | `0` (recomputed by the controller) | Documented practice of offline generators |
| Instruction line | `   1:  UFRAME_NUM=0 ;` (number on 4 columns, 2 spaces) | Confirmed |
| Motion line | `   4:J P[1] 100% FINE    ;` (motion letter right after `:`) | Confirmed |
| Empty line | `   6:   ;` | Confirmed |
| Empty program | `/MN` immediately followed by `/POS` | Confirmed |

## Instructions

| TP | Example | Status |
|---|---|---|
| Joint / linear motion | `J P[1] 50% CNT50`, `L P[2] 500mm/sec FINE` | Confirmed (`J`, `%`, `FINE`); `L`/`mm/sec`/`CNT` documented |
| Circular motion | `C P[2]` + continuation line `    :  P[3] 200mm/sec FINE    ;` | Documented |
| Frames | `UFRAME_NUM=1`, `UTOOL_NUM=2` | Confirmed |
| Digital output | `DO[1]=ON` | Confirmed |
| Register | `R[3:nCycles]=R[3:nCycles]+1` | Confirmed (`R[n:comment]=value`); arithmetic documented |
| Flag | `F[1:bDone]=(ON)` (parentheses) | Confirmed |
| Remark | `!text` (no parentheses in `.LS`) | Confirmed |
| Label / jump | `LBL[1]`, `JMP LBL[1]` | Confirmed |
| Call | `CALL PICK` | Confirmed |
| Pause / abort | `PAUSE`, `ABORT` | Confirmed |
| End | `END` | Documented |
| Mixed-logic IF block | `IF (R[1:n]=1 AND DI[2]=ON) THEN` / `ELSE` / `ENDIF` | Documented |
| FOR loop | `FOR R[1:i]=1 TO 3` / `ENDFOR` | Documented |
| Waits | `WAIT 0.50(sec)`, `WAIT R[1]`, `WAIT DI[1]=ON`, `WAIT (cond)` | Documented |

## `/POS` section

Joint position (**confirmed**, byte-exact):

```
P[1]{
   GP1:
	UF : 0, UT : 1,	
	J1=     0.000 deg,	J2=   -30.000 deg,	J3=    30.000 deg,
	J4=     0.000 deg,	J5=    90.000 deg,	J6=     0.000 deg
};
```

Cartesian position (**documented**, not yet seen in this project's exports):

```
P[2]{
   GP1:
	UF : 0, UT : 2,		CONFIG : 'N U T, 0, 0, 0',
	X =   600.000  mm,	Y =     0.000  mm,	Z =   900.000  mm,
	W =   180.000 deg,	P =     0.000 deg,	R =   180.000 deg
};
```

## Known limits

* The arm configuration is not transferred. ABB `confdata` and FANUC `CONFIG` describe
  different kinematics, so every point uses `'N U T, 0, 0, 0'` and a warning is raised.
* Joint targets (`MoveAbsJ`) are copied axis by axis. Axis zero positions and the J2/J3
  convention differ between the brands, so these points must be re-taught.
* No `P[n]` comment is emitted (`P[1:HOME]`). The layout of commented points in `/POS`
  is not confirmed. The report maps every `P[n]` back to its RAPID name instead.

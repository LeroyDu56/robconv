# robconv

Cross-brand industrial robot program converter, starting with **ABB RAPID → FANUC TP**.

> **Status: V1 — read-only.** robconv parses RAPID modules into an AST and prints it as
> JSON or as a readable listing. FANUC `.LS` generation is planned for V2. Even then, the output
> will be a text listing to import and check in ROBOGUIDE or on the teach pendant. It is not
> a directly executable `.TP` binary.

Pure Python, **no runtime dependency**. Tested against real controller backups
(RobotWare 7, ~10,000 lines across 24 modules: zero syntax errors).

## Quick start

```bash
pip install -e ".[dev]"

robconv parse tests/fixtures/rapid/pick_and_place.mod              # readable listing
robconv parse tests/fixtures/rapid/pick_and_place.mod --format json
robconv stats path/to/backup/RAPID                                  # coverage report
```

```
   53 |   PROC Place()
   54 |     pPlace := Offs(pHome, nOffsets{nSlot}, 0, -400)
   56 |     IF nSlot = 1 THEN
   57 |       MOVE J     to=pPlace  speed=v800  zone=z20  tool=tGripper  wobj=wobjFixture
      |     ELSEIF nSlot = 2 THEN
   59 |       MOVE C     via=pArcMid  to=pArcEnd  speed=v300  zone=z10  tool=tGripper  wobj=wobjFixture
      |     ELSE
   61 |       MOVE L     to=pPlace  speed=v300  zone=fine  tool=tGripper  wobj=wobjFixture
      |     ENDIF
   63 |     SET       DO_GripperClose = 0
   64 |     WAIT      0.2 s  \InPos
   65 |     ?? [GOTO] GOTO skip_log;
```

## V1 scope

| Recognised as typed nodes | Parsed structurally | Kept as `Unsupported` (raw text preserved) |
|---|---|---|
| `MoveJ` `MoveL` `MoveC` `MoveAbsJ` (arguments by role) | `WHILE`, `TEST/CASE` | `RECORD`, `ALIAS` |
| `Set` / `Reset` | `RETURN`, `EXIT` | `ERROR` / `UNDO` / `BACKWARD` handlers |
| `WaitTime` | calls with arguments | `GOTO` and labels, `RAISE`, `RETRY`, `TRYNEXT` |
| `IF / ELSEIF / ELSE` (and one-line `IF`) | `FUNC`, `TRAP` | `CONNECT` (interrupts) |
| `FOR ... STEP` | routine parameters (raw text) | late-binding calls `%"name"%` |
| assignments, `CONST/VAR/PERS` data (robtargets...) | | |
| comments | | |

Robustness: one unreadable statement becomes a `SYNTAX_ERROR` node plus a diagnostic,
and parsing continues. See [docs/design.md](docs/design.md).

## Layout

```
src/robconv/
  cli.py              robconv parse / stats
  diagnostics.py      Span, Diagnostic
  rapid/
    source.py         encoding detection (UTF-8 / cp1252), CRLF
    tokens.py lexer.py
    nodes.py          AST (frozen dataclasses)
    parser.py         recursive descent — grammar in docs/rapid_grammar_v1.ebnf
    to_json.py to_pseudo.py
tests/
  rapid/              unit, recovery, golden and private-corpus tests
  fixtures/rapid/     synthetic .mod files + expected JSON
```

## Tests

```bash
pytest                                            # unit + golden tests
ROBCONV_PRIVATE_CORPUS=/path/to/backups pytest    # + real programs (never committed)
ROBCONV_UPDATE_GOLDEN=1 pytest tests/rapid/test_golden.py   # regenerate expected JSON
```

## Roadmap

- **V2**: RAPID → FANUC mapping (quaternion → WPR, zonedata → CNT/FINE, wobj/tool names →
  UFRAME/UTOOL numbers) and `.LS` writer.
- Parameterised routines, `CALL` with arguments.

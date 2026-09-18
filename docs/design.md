# Design notes

## Pipeline

```
 .mod/.modx bytes ──► source.py ──► lexer.py ──► parser.py ──► nodes.Module ──► to_json.py / to_pseudo.py
                     decode        tokens +      recursive                        (V2: mapping ──► FANUC .LS writer)
                     CRLF→LF       comments      descent
```

| File | Role |
|---|---|
| `rapid/source.py` | Bytes → text. UTF-8 (RobotWare 7) with Windows-1252 fallback (older exports), CRLF normalised. |
| `rapid/tokens.py` | Token kinds, reserved words, operators. |
| `rapid/lexer.py` | Text → tokens. Comments are kept in a side list. Never raises. |
| `rapid/nodes.py` | Immutable AST (frozen dataclasses). Faithful to RAPID, no FANUC concept. |
| `rapid/parser.py` | Recursive descent, one method per rule of `docs/rapid_grammar_v1.ebnf`. |
| `rapid/to_json.py` | Generic dataclass → JSON serialiser. |
| `rapid/to_pseudo.py` | Readable listing with source line numbers. |
| `cli.py` | `robconv parse`, `robconv stats`. |

## Decisions

**Hand-written parser, no dependency.** Real programs are far bigger than the
V1 subset (records, error handlers, late binding...). A hand-written parser
makes it trivial to skip such a construct as a whole and keep going, with
precise error positions. Grammar generators make that kind of recovery much harder.

**Parse generically, then specialise.** Every instruction is parsed as a
procedure call (`name args;`). Only then are `MoveJ/MoveL/MoveC/MoveAbsJ`,
`Set/Reset` and `WaitTime` turned into typed nodes, with their arguments named
by role (`to_point`, `speed`, `zone`, `tool`, `wobj`). A call with an unexpected
shape stays a generic `ProcCall` and gets a warning, so nothing is guessed.

**Structure beyond V1 is parsed, not dropped.** `WHILE` and `TEST` are outside
the V1 conversion scope, but a real main routine is typically one big
`WHILE TRUE DO` loop. Parsing them keeps the V1 instructions inside visible.

**Nothing is lost silently.** Out-of-scope constructs become `Unsupported`
nodes with a stable `kind` tag and their exact source text. `robconv stats`
counts them across a whole backup to decide what to support next.

**Error recovery levels.**
1. Statement: rewind, skip one statement (balancing `IF…ENDIF` etc., never
   crossing the parent's closing keyword), emit `SYNTAX_ERROR` + diagnostic.
2. Routine: if the block structure itself is broken, the routine is skipped up
   to its `ENDPROC/ENDFUNC/ENDTRAP`. Other routines are unaffected.
3. Module: a missing `MODULE` header returns no module plus an error.

**Comments** are re-inserted between statements by source position. A
trailing comment becomes a `Comment` node right after its statement, on the
same line. Comments inside a skipped construct stay in its raw text.

## Testing

* Unit tests per layer (source, lexer, declarations, statements, recovery).
* Golden tests: each `tests/fixtures/rapid/*.mod` has an `.expected.json`.
  Fixtures are synthetic (written from scratch), CRLF, one in cp1252 with a
  legacy `%%%` header.
* Private corpus: real controller backups are client-confidential and never
  committed. `test_private_corpus.py` parses every file under
  `$ROBCONV_PRIVATE_CORPUS` (default `./abb`, git-ignored) and asserts zero
  syntax errors; it is skipped when no corpus is present.

"""RAPID -> TP translation rules, one behaviour per test."""

from datetime import datetime

import pytest
from helpers import parse_module

from robconv.convert import ConversionConfig, convert
from robconv.fanuc.tp import CartesianPosition, Instruction, JointPosition, Motion

HOME = "CONST robtarget pHome:=[[600,0,900],[0,1,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];"
TOOL = "PERS tooldata tGrip:=[TRUE,[[0,0,185.5],[1,0,0,0]],[2.4,[0,0,90],[1,0,0,0],0,0,0]];"
WOBJ = 'PERS wobjdata wFix:=[FALSE,TRUE,"",[[1000,0,0],[1,0,0,0]],[[0,0,100],[1,0,0,0]]];'


def run(body: str, data: str = "", config: ConversionConfig | None = None, extra_procs: str = ""):
    source = f"MODULE M\n{data}\nPROC main()\n{body}\nENDPROC\n{extra_procs}\nENDMODULE\n"
    config = config or ConversionConfig(timestamp=datetime(2026, 1, 1))
    return convert([parse_module(source)], config, routines=["main"], sources={"M": source})


def tp_lines(result) -> list[str]:
    """Program lines as text, without the leading '!RAPID M.main' remark."""
    out = []
    for line in result.programs[0].program.lines[1:]:
        if isinstance(line, Motion):
            via = f" {line.via}" if line.via else ""
            out.append(f"{line.kind}{via} {line.target} {line.speed} {line.termination}")
        else:
            out.append(line.text)
    return out


def todos(result) -> list[str]:
    return [note.message for note in result.notes if note.kind == "TODO"]


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


def test_movel_emits_frames_then_motion_and_cartesian_point():
    result = run("MoveL pHome,v500,z10,tGrip\\WObj:=wFix;", HOME + TOOL + WOBJ)
    assert tp_lines(result) == ["UFRAME_NUM=1", "UTOOL_NUM=1", "L P[1] 500mm/sec CNT10"]
    (pos,) = result.programs[0].program.positions
    assert (pos.uf, pos.ut) == (1, 1)
    assert pos.value == CartesianPosition(600, 0, 900, 180, 0, 0)


def test_frames_are_only_emitted_when_they_change():
    result = run("MoveJ pHome,v1000,z50,tGrip;\nMoveL pHome,v100,fine,tGrip;", HOME + TOOL)
    assert tp_lines(result) == ["UFRAME_NUM=0", "UTOOL_NUM=1", "J P[1] 50% CNT50", "L P[1] 100mm/sec FINE"]


def test_same_target_reuses_the_same_point():
    result = run("MoveJ pHome,v1000,fine,tool0;\nMoveJ pHome,v1000,fine,tool0;", HOME)
    assert len(result.programs[0].program.positions) == 1


def test_offs_is_computed_at_conversion_time():
    result = run("MoveL Offs(pHome,10,-20,30),v100,fine,tool0;", HOME)
    value = result.programs[0].program.positions[0].value
    assert (value.x, value.y, value.z) == (610, -20, 930)


def test_reltool_moves_along_the_tool_axis():
    # Tool pointing down: +100 along tool Z is -100 in Z of the work object.
    result = run("MoveL RelTool(pHome,0,0,100),v100,fine,tool0;", HOME)
    assert result.programs[0].program.positions[0].value.z == pytest.approx(800)


def test_movec_has_via_and_target_points():
    data = HOME + "CONST robtarget pEnd:=[[700,100,900],[0,1,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];"
    result = run("MoveC pHome,pEnd,v200,z5,tool0;", data)
    assert tp_lines(result)[-1] == "C P[1] P[2] 200mm/sec CNT5"


def test_moveabsj_becomes_joint_point_with_warning():
    data = "CONST jointtarget jPark:=[[0,-30,30,0,90,0],[9E9,9E9,9E9,9E9,9E9,9E9]];"
    result = run("MoveAbsJ jPark\\NoEOffs,v500,fine,tool0;", data)
    # Measured conventions: J3 absolute = -(J2 + J3), J4/J5 reversed, J6 = 180 - J6.
    assert result.programs[0].program.positions[0].value == JointPosition((0, -30, 0, 0, -90, 180))
    assert any("joint targets" in n.message for n in result.notes if n.kind == "WARNING")


def test_joint_mapping_can_be_disabled():
    data = "CONST jointtarget jPark:=[[0,-30,30,0,90,0],[9E9,9E9,9E9,9E9,9E9,9E9]];"
    config = ConversionConfig(joint_mapping=False, timestamp=datetime(2026, 1, 1))
    result = run("MoveAbsJ jPark,v500,fine,tool0;", data, config)
    assert result.programs[0].program.positions[0].value == JointPosition((0, -30, 30, 0, 90, 0))


def test_custom_speeddata_and_zonedata_are_resolved():
    data = HOME + "PERS speeddata vSlow:=[250,30,500,50];\nCONST zonedata zBig:=[FALSE,120,150,150,15,150,15];"
    result = run("MoveJ pHome,vSlow,zBig,tool0;\nMoveL pHome,vSlow,zBig,tool0;", data)
    assert tp_lines(result)[-2:] == ["J P[1] 13% CNT100", "L P[1] 250mm/sec CNT100"]


def test_speed_heuristic_is_configurable():
    config = ConversionConfig(joint_speed_ref_mm_s=1000, timestamp=datetime(2026, 1, 1))
    result = run("MoveJ pHome,v500,fine,tool0;", HOME, config)
    assert tp_lines(result)[-1] == "J P[1] 50% FINE"


def test_target_set_at_run_time_becomes_todo_without_orphan_point():
    result = run("pTmp:=pHome;\nMoveL pTmp,v100,fine,tool0;", HOME + "VAR robtarget pTmp;")
    assert result.programs[0].program.positions == []
    assert [line.startswith("!TODO l.") for line in tp_lines(result)] == [True, True]
    assert "set at run time" in todos(result)[1]


def test_untranslatable_move_keeps_the_rapid_source_in_the_remark():
    result = run("MoveL pUnknown,v100,fine,tool0;")
    assert tp_lines(result) == ["!TODO l.4 MoveL pUnknown,v100,fin"]  # 32 characters


# ---------------------------------------------------------------------------
# I/O, waits, calls
# ---------------------------------------------------------------------------


def test_set_reset_setdo_share_one_output_number():
    result = run("Set doGrip;\nReset doGrip;\nSetDO doGrip,1;")
    assert tp_lines(result) == ["DO[1]=ON", "DO[1]=OFF", "DO[1]=ON"]


def test_mapping_file_pins_numbers(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text('{"digital_outputs": {"DOGRIP": 12}, "utools": {"tGrip": 5}}', encoding="utf-8")
    config = ConversionConfig.from_mapping_file(mapping, timestamp=datetime(2026, 1, 1))
    result = run("Set doGrip;\nMoveJ pHome,v1000,fine,tGrip;", HOME + TOOL, config)
    assert tp_lines(result)[:3] == ["DO[12]=ON", "UFRAME_NUM=0", "UTOOL_NUM=5"]
    assert result.digital_outputs[0].fixed


def test_unknown_mapping_key_is_rejected(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text('{"registres": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="registres"):
        ConversionConfig.from_mapping_file(mapping)


def test_comments_follow_controller_rules():
    # Register comments survive only on registers the programs write; flag comments never.
    result = run("n:=1;\nIF m=2 AND bOk Stop;", "VAR num n;\nVAR num m;\nVAR bool bOk;")
    assert tp_lines(result) == ["R[1:n]=1", "IF (R[2]=2 AND F[1]=ON) THEN", "PAUSE", "ENDIF"]


def test_waits():
    result = run("WaitTime 0.5;\nWaitDI diReady,1;\nWaitUntil diReady=0 AND nCount>2;", "VAR num nCount;")
    assert tp_lines(result) == ["WAIT    .50(sec)", "WAIT DI[1]=ON", "WAIT (DI[1]=OFF AND R[1]>2)"]


def test_waittime_on_a_variable_uses_the_register():
    assert tp_lines(run("WaitTime tDelay;", "PERS num tDelay:=2;")) == ["WAIT R[1]"]


def test_calls_stop_return_exit():
    result = run("Sub;\nStop;\nRETURN;\nEXIT;", extra_procs="PROC Sub()\nENDPROC")
    assert tp_lines(result) == ["CALL SUB", "PAUSE", "END", "ABORT"]


def test_call_with_arguments_is_a_todo():
    result = run("Grip 3;")
    assert tp_lines(result) == ["!TODO l.4 Grip 3"]
    assert "with arguments" in todos(result)[0]


def test_tpwrite_fixed_text_becomes_message():
    result = run('TPErase;\nTPWrite "Cycle [A] start";\nTPWrite "Part "+"done";\nTPWrite "";')
    assert tp_lines(result) == ["MESSAGE[Cycle (A) start]", "MESSAGE[Part done]"]


def test_tpwrite_constant_and_long_text():
    result = run('TPWrite MSG;\nTPWrite "A message that is far too long for the pendant";', 'CONST string MSG:="Ready";')
    assert tp_lines(result) == ["MESSAGE[Ready]", "MESSAGE[A message that is far to]"]  # 24 characters
    assert any("cut to 24" in n.message for n in result.notes)


def test_tpwrite_with_a_value_stays_a_todo():
    result = run('TPWrite "Count: "\\Num:=n;\nTPWrite "Code "+ValToStr(n);', "VAR num n;")
    assert [line.startswith("!TODO") for line in tp_lines(result)] == [True, True]
    assert all("variable" in m or "run time" in m for m in todos(result))


def test_group_outputs_and_inputs():
    result = run("n:=GInput(giCode);\nSetGO goEcho,n;\nSetGO goStatus,3;", "VAR num n;")
    assert tp_lines(result) == ["R[1:n]=GI[1]", "GO[1]=R[1:n]", "GO[2]=3"]
    assert [a.rapid_name for a in result.group_outputs] == ["goEcho", "goStatus"]


# ---------------------------------------------------------------------------
# Data and control flow
# ---------------------------------------------------------------------------


def test_num_and_bool_data_become_registers_and_flags():
    data = "PERS num nCycles:=0;\nVAR bool bDone:=FALSE;\nCONST num MAX:=3;"
    result = run("nCycles:=nCycles+1;\nnCycles:=MAX*2;\nbDone:=TRUE;", data)
    assert tp_lines(result) == ["R[1:nCycles]=R[1:nCycles]+1", "R[1:nCycles]=6", "F[1]=(ON)"]
    assert "initial value 0" in result.registers[0].detail


def test_if_elseif_else_is_unrolled_into_nested_ifs():
    result = run("IF n=1 THEN\n  Set doA;\nELSEIF n=2 THEN\n  Set doB;\nELSE\n  Reset doA;\nENDIF", "VAR num n;")
    assert tp_lines(result) == [
        "IF (R[1]=1) THEN", "DO[1]=ON",
        "ELSE",
        "IF (R[1]=2) THEN", "DO[2]=ON",
        "ELSE", "DO[1]=OFF",
        "ENDIF",
        "ENDIF",
    ]  # fmt: skip


def test_conditions_negation_is_pushed_down():
    result = run("IF NOT (n>2 AND diOk=1) Set doA;", "VAR num n;")
    assert tp_lines(result)[0] == "IF (R[1]<=2 OR DI[1]=OFF) THEN"


def test_signal_functions_in_conditions():
    result = run("IF DOutput(doA)=1 AND DInput(diB)=0 THEN\nENDIF")
    assert tp_lines(result)[0] == "IF (DO[1]=ON AND DI[1]=OFF) THEN"


def test_for_loops():
    result = run("FOR i FROM 1 TO 3 DO\n  n:=i;\nENDFOR\nFOR k FROM 5 TO 1 STEP -1 DO\nENDFOR", "VAR num n;")
    assert tp_lines(result) == [
        "FOR R[1:i]=1 TO 3", "R[2:n]=R[1:i]", "ENDFOR",
        "FOR R[3:k]=5 DOWNTO 1", "ENDFOR",
    ]  # fmt: skip


def test_for_with_other_step_is_a_todo():
    assert "STEP" in todos(run("FOR i FROM 0 TO 10 STEP 2 DO\nENDFOR"))[0]


def test_while_loops_use_labels():
    assert tp_lines(run("WHILE TRUE DO\n  Stop;\nENDWHILE")) == ["LBL[1]", "PAUSE", "JMP LBL[1]"]
    result = run("WHILE n<3 DO\n  n:=n+1;\nENDWHILE", "VAR num n;")
    assert tp_lines(result) == [
        "LBL[1]", "IF (R[1:n]>=3) THEN", "JMP LBL[2]", "ENDIF",
        "R[1:n]=R[1:n]+1", "JMP LBL[1]", "LBL[2]",
    ]  # fmt: skip


def test_comments_are_split_to_32_characters():
    result = run("! " + "word " * 12)
    lines = tp_lines(result)
    assert len(lines) == 2 and all(len(line) <= 33 for line in lines)


def test_accents_are_folded_to_ascii():
    assert tp_lines(run("! réglage opérateur")) == ["! reglage operateur"]


# ---------------------------------------------------------------------------
# Program level
# ---------------------------------------------------------------------------


def test_routine_selection_and_skipped_routines():
    source = "MODULE M\nPROC a()\nENDPROC\nPROC b(num x)\nENDPROC\nFUNC num f()\nRETURN 1;\nENDFUNC\nENDMODULE"
    result = convert([parse_module(source)], ConversionConfig(timestamp=datetime(2026, 1, 1)))
    assert [p.program.name for p in result.programs] == ["A"]
    assert [(r, why.split(" ")[0]) for _, r, why in result.skipped_routines] == [("b", "routine"), ("f", "FUNC")]


def test_system_modules_are_data_only_unless_requested():
    sys_module = parse_module(f"MODULE D(SYSMODULE)\n{HOME}\nPROC util()\nENDPROC\nENDMODULE")
    prog = parse_module("MODULE P\nPROC main()\nMoveJ pHome,v100,fine,tool0;\nENDPROC\nENDMODULE")
    result = convert([sys_module, prog], ConversionConfig(timestamp=datetime(2026, 1, 1)))
    assert [p.program.name for p in result.programs] == ["MAIN"]
    assert result.todo_count == 0  # pHome resolved from the system module


def test_program_names_are_sanitised_and_unique():
    source = "MODULE M\nPROC go_to_home()\nENDPROC\nLOCAL PROC Go_To_Home2()\nENDPROC\nENDMODULE"
    result = convert([parse_module(source)], ConversionConfig(program_name_max_length=8, timestamp=datetime(2026, 1, 1)))
    assert [p.program.name for p in result.programs] == ["GO_TO_HO", "GO_TO__2"]


def test_first_line_names_the_rapid_origin():
    result = run("Stop;")
    assert result.programs[0].program.lines[0] == Instruction("!RAPID M.main")

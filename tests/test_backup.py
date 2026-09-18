"""Backup detection, zip handling and the full pipeline, on a synthetic two-robot backup."""

import zipfile
from pathlib import Path

import pytest

from robconv.backup import find_backup_root, open_source
from robconv.convert.html import markdown_to_html
from robconv.pipeline import run, unique_folder

DATA_MODULE = (
    "MODULE Cell_Data(SYSMODULE)\n"
    "  CONST robtarget pHome:=[[600,0,900],[0,1,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];\n"
    "  PROC Util()\n  ENDPROC\n"
    "ENDMODULE\n"
)


def program(name: str, output: str) -> str:
    return f"MODULE {name}\n  PROC main()\n    MoveJ pHome,v1000,fine,tool0;\n    Set {output};\n  ENDPROC\nENDMODULE\n"


def make_backup(root: Path) -> Path:
    """Two tasks, folders numbered like a real controller (TASK1 = T_ROB1, TASK2 = T_ROB2)."""
    (root / "BACKINFO").mkdir(parents=True)
    (root / "BACKINFO" / "backinfo.txt").write_text(
        ">>SYSTEM_ID:\nCell\n\n>>TASK1: (T_ROB1,,)\nSYSMOD/Cell_Data.sys @\n\n>>TASK2: (T_ROB2,,)\n\n>>EOF:\n"
    )
    for task, robot in (("TASK1", "Robot1"), ("TASK2", "Robot2")):
        (root / "RAPID" / task / "PROGMOD").mkdir(parents=True)
        (root / "RAPID" / task / "SYSMOD").mkdir(parents=True)
        (root / "RAPID" / task / "PROGMOD" / f"{robot}.mod").write_text(program(robot, "gripClose"))
        (root / "RAPID" / task / "SYSMOD" / "Cell_Data.sys").write_text(DATA_MODULE)
    (root / "SYSPAR").mkdir()
    (root / "SYSPAR" / "EIO.cfg").write_text('EIO_SIGNAL:\n\n  -Name "gripClose" -SignalType "DO" -DeviceMap "4"\n')
    (root / "HOME").mkdir()
    (root / "HOME" / "notes.txt").write_text("not RAPID")
    (root / "users.bin").write_bytes(b"\x00\x01")
    return root


def zip_folder(folder: Path, archive: Path) -> Path:
    with zipfile.ZipFile(archive, "w") as z:
        for path in folder.rglob("*"):
            z.write(path, path.relative_to(folder.parent))  # keeps the top folder, like Windows "Send to zip"
    return archive


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_backup_is_split_by_task_with_controller_names(tmp_path):
    backup = make_backup(tmp_path / "Cell_2026")
    with open_source([backup]) as source:
        assert (source.kind, source.name) == ("backup", "Cell_2026")
        assert [t.name for t in source.tasks] == ["T_ROB1", "T_ROB2"]
        task = source.tasks[0]
        assert [p.name for p in task.program_files] == ["Robot1.mod"]
        assert [p.name for p in task.data_files] == ["Cell_Data.sys"]
        assert source.eio == backup / "SYSPAR" / "EIO.cfg"


def test_picking_the_rapid_folder_finds_the_backup(tmp_path):
    backup = make_backup(tmp_path / "Cell")
    with open_source([backup / "RAPID"]) as source:
        assert source.kind == "backup" and len(source.tasks) == 2


def test_task_folder_name_is_kept_without_backinfo(tmp_path):
    backup = make_backup(tmp_path / "Cell")
    (backup / "BACKINFO" / "backinfo.txt").unlink()
    with open_source([backup]) as source:
        assert [t.name for t in source.tasks] == ["TASK1", "TASK2"]


def test_zipped_backup_is_extracted_then_cleaned_up(tmp_path):
    archive = zip_folder(make_backup(tmp_path / "Cell"), tmp_path / "Cell_backup.zip")
    with open_source([archive]) as source:
        assert (source.kind, source.name, source.location) == ("backup", "Cell_backup", tmp_path)
        extracted = source.tasks[0].program_files[0]
        assert extracted.exists()
    assert not extracted.exists()


def test_zip_slip_is_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../outside.mod", "MODULE X\nENDMODULE\n")
    with pytest.raises(ValueError, match="unsafe path"), open_source([archive]):
        pass
    assert not (tmp_path / "outside.mod").exists()


def test_loose_files_make_one_task(tmp_path):
    a = tmp_path / "a.mod"
    a.write_text(program("A", "doA"))
    with open_source([a]) as source:
        assert (source.kind, source.name, [t.name for t in source.tasks]) == ("files", "a", ["files"])


def test_not_a_backup_folder(tmp_path):
    assert find_backup_root(tmp_path) is None


def test_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError), open_source([tmp_path / "nope"]):
        pass


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_full_backup_conversion(tmp_path):
    backup = make_backup(tmp_path / "Cell")
    logs: list[str] = []
    result = run([backup], log=logs.append)

    assert result.folder == tmp_path / "robconv_Cell"  # next to the backup
    assert [t.task for t in result.tasks] == ["T_ROB1", "T_ROB2"]
    for task in ("T_ROB1", "T_ROB2"):
        files = sorted(p.name for p in (result.folder / task).iterdir())
        # System module routines are not converted; data (pHome) is still resolved.
        assert files == ["MAIN.LS", "robconv_report.html", "robconv_report.md"]
    ls = (result.folder / "T_ROB1" / "MAIN.LS").read_text(encoding="ascii")
    assert "DO[1]=ON" in ls and "J P[1]" in ls
    assert result.todo == 0
    assert any("EIO.cfg" in line for line in logs)
    detail = (result.folder / "T_ROB1" / "robconv_report.md").read_text(encoding="utf-8")
    assert "EIO.cfg: DO" in detail


def test_second_run_never_overwrites(tmp_path):
    backup = make_backup(tmp_path / "Cell")
    first, second = run([backup], log=lambda _: None), run([backup], log=lambda _: None)
    assert (first.folder.name, second.folder.name) == ("robconv_Cell", "robconv_Cell_2")
    assert unique_folder(tmp_path / "fresh") == tmp_path / "fresh"


def test_syntax_errors_are_reported_not_fatal(tmp_path):
    bad = tmp_path / "bad.mod"
    bad.write_text("MODULE Bad\n  PROC main()\n    x := ;\n    Stop;\n  ENDPROC\nENDMODULE\n")
    result = run([bad], log=lambda _: None)
    assert result.programs == 1
    assert result.tasks[0].syntax_errors
    assert "Syntax errors" in (result.folder / "robconv_report.md").read_text(encoding="utf-8")


def test_no_rapid_file(tmp_path):
    (tmp_path / "readme.txt").write_text("hello")
    with pytest.raises(ValueError, match="no RAPID module"):
        run([tmp_path], log=lambda _: None)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def test_html_report_renders_the_markdown_subset():
    md = (
        "# Title <x>\n\n> **Warning** text\n\n- item `a|b`\n\n"
        "| Program | Kind | Detail |\n|---|---|---|\n| MAIN | TODO | pipe \\| inside |\n\n_None._\n"
    )
    page = markdown_to_html(md, "t")
    assert "<h1>Title &lt;x&gt;</h1>" in page
    assert "<blockquote><p><strong>Warning</strong> text</p></blockquote>" in page
    assert "<li>item <code>a|b</code></li>" in page
    assert '<td class="kind-TODO">TODO</td>' in page
    assert "<td>pipe | inside</td>" in page
    assert '<p class="muted">None.</p>' in page

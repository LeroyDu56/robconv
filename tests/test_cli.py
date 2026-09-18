import json

from robconv.cli import main


def test_parse_pseudo(fixtures_dir, capsys):
    assert main(["parse", str(fixtures_dir / "rapid" / "pick_and_place.mod")]) == 0
    out = capsys.readouterr().out
    assert "MOVE C     via=pArcMid  to=pArcEnd" in out
    assert "?? [RECORD]" in out


def test_parse_json_to_file(fixtures_dir, tmp_path):
    out = tmp_path / "out.json"
    assert main(["parse", str(fixtures_dir / "rapid" / "legacy_header.mod"), "--format", "json", "-o", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["encoding"] == "cp1252"
    assert data["module"]["name"] == "Legacy_Palette"


def test_parse_reports_errors_with_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.mod"
    bad.write_text("MODULE B\nPROC p()\n  x := ;\nENDPROC\nENDMODULE\n", encoding="utf-8")
    assert main(["parse", str(bad)]) == 1
    assert "3:" in capsys.readouterr().err


def test_missing_file(tmp_path, capsys):
    assert main(["parse", str(tmp_path / "nope.mod")]) == 2


def test_stats(fixtures_dir, capsys):
    assert main(["stats", str(fixtures_dir / "rapid")]) == 0
    out = capsys.readouterr().out
    assert "2 files, 0 errors" in out
    assert "ERROR_HANDLER" in out

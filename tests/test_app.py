"""Desktop entry point without a window (the GUI itself needs a display)."""

from robconv.app import main


def test_headless_conversion_of_dropped_files(tmp_path, fixtures_dir, monkeypatch, capsys):
    source = tmp_path / "pick_and_place.mod"
    source.write_bytes((fixtures_dir / "rapid" / "pick_and_place.mod").read_bytes())
    monkeypatch.setenv("ROBCONV_NO_GUI", "1")
    assert main([str(source)]) == 0
    assert (tmp_path / "robconv_pick_and_place" / "MAIN.LS").exists()
    assert "3 programs" in capsys.readouterr().out

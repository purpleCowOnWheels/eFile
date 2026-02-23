"""CLI smoke tests — verify all commands load and respond to --help."""

from __future__ import annotations

from typer.testing import CliRunner

from pfile.cli.main import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pfile" in result.output.lower()


def test_new_help():
    result = runner.invoke(app, ["new", "--help"])
    assert result.exit_code == 0
    assert "filing session" in result.output.lower()


def test_compute_help():
    result = runner.invoke(app, ["compute", "--help"])
    assert result.exit_code == 0
    assert "session" in result.output.lower()


def test_show_help():
    result = runner.invoke(app, ["show", "--help"])
    assert result.exit_code == 0


def test_generate_help():
    result = runner.invoke(app, ["generate", "--help"])
    assert result.exit_code == 0
    assert "session_id" in result.output.lower()


def test_generate_help_shows_out_option():
    result = runner.invoke(app, ["generate", "--help"])
    assert "--out" in result.output


def test_list_help():
    result = runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0


def test_ingest_help():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0


def test_add_doc_help():
    result = runner.invoke(app, ["add-doc", "--help"])
    assert result.exit_code == 0


def test_resume_help():
    result = runner.invoke(app, ["resume", "--help"])
    assert result.exit_code == 0


def test_missing_session_exits_cleanly(tmp_path, monkeypatch):
    """Running compute with a bad session ID exits with code 1, not a traceback."""
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["compute", "does-not-exist"])
    assert result.exit_code == 1

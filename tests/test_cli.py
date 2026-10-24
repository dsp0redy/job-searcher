from __future__ import annotations

import json
import sys

import pytest

import job_searcher.cli as cli


class FakeConfig:
    def model_dump(self):
        return {"matching": {"provider": "none"}}


def test_cli_check_config_prints_validated_config(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["job-searcher", "--config", "sample.yml", "--check-config"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    monkeypatch.setattr(cli, "SearchOrchestrator", lambda config: pytest.fail("scan should not run"))
    cli.main()
    output = capsys.readouterr().out
    assert "Configuration valid" in output
    assert json.loads(output.split("\n", 1)[1]) == {"matching": {"provider": "none"}}


def test_cli_runs_scan_and_prints_summary(monkeypatch, capsys):
    summary = {"run_status": "success", "qualified_candidates": 2}
    monkeypatch.setattr(sys, "argv", ["job-searcher", "--config", "sample.yml", "--output-dir", "out"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    class FakeOrchestrator:
        def __init__(self, config): pass
        def run(self, output_dir): 
            assert output_dir == "out"
            return summary
    monkeypatch.setattr(cli, "SearchOrchestrator", FakeOrchestrator)
    cli.main()
    assert json.loads(capsys.readouterr().out) == summary


def test_cli_partial_ai_failure_exits_nonzero_after_report(monkeypatch, capsys):
    summary = {"run_status": "partial_ai_failure"}
    monkeypatch.setattr(sys, "argv", ["job-searcher"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    class FakeOrchestrator:
        def __init__(self, config): pass
        def run(self, output_dir): return summary
    monkeypatch.setattr(cli, "SearchOrchestrator", FakeOrchestrator)
    with pytest.raises(SystemExit, match="AI matching was incomplete"):
        cli.main()
    assert json.loads(capsys.readouterr().out) == summary


def test_cli_verbose_enables_debug_logging(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["job-searcher", "--verbose", "--check-config"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    cli.main()
    assert "Configuration valid" in capsys.readouterr().out

def test_cli_module_entrypoint_executes_check_config(monkeypatch, capsys):
    import runpy
    import warnings
    monkeypatch.setattr(sys, "argv", ["job-searcher", "--config", "config.yml", "--check-config"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("job_searcher.cli", run_name="__main__")
    assert "Configuration valid" in capsys.readouterr().out




def test_cli_no_successful_sources_exits_nonzero(monkeypatch, capsys):
    summary = {"run_status": "no_sources_succeeded"}
    monkeypatch.setattr(sys, "argv", ["job-searcher"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    class FakeOrchestrator:
        def __init__(self, config): pass
        def run(self, output_dir): return summary
    monkeypatch.setattr(cli, "SearchOrchestrator", FakeOrchestrator)
    with pytest.raises(SystemExit, match="No configured job sources"):
        cli.main()
    assert json.loads(capsys.readouterr().out) == summary



def test_cli_resume_preview_is_local_and_does_not_run_scan(monkeypatch, capsys):
    monkeypatch.setenv("RESUME_TEXT", "Experienced C++ and Linux engineer " * 8)
    monkeypatch.setattr(sys, "argv", ["job-searcher", "--preview-resume"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    monkeypatch.setattr(cli, "SearchOrchestrator", lambda config: pytest.fail("scan should not run"))
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["characters"] > 80
    assert result["quality_warning"] is False
    assert result["network_requests_made"] is False
    assert result["truncated"] is True


def test_cli_resume_preview_reports_missing_resume(monkeypatch, capsys):
    monkeypatch.delenv("RESUME_TEXT", raising=False)
    monkeypatch.delenv("RESUME_FILE", raising=False)
    monkeypatch.setattr(sys, "argv", ["job-searcher", "--preview-resume"])
    monkeypatch.setattr(cli.AppConfig, "load", lambda path: FakeConfig())
    with pytest.raises(SystemExit, match="RESUME_TEXT or RESUME_FILE"):
        cli.main()

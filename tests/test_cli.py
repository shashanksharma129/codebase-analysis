from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.cli import analyze


def _make_final_output():
    from src.models import DomainAnalysis, FinalOutput, ProjectInfo, ProjectSummary
    return FinalOutput(
        language="java",
        project=ProjectInfo(
            name="test", overview="o", purpose="p",
            tech_stack=[], architecture_pattern="MVC",
        ),
        domains=[],
        summary=ProjectSummary(
            total_files=0, total_domains=0, total_methods=0,
            overall_complexity="low", key_patterns=[], notable_aspects=[],
        ),
    )


@pytest.fixture
def source_dir(tmp_path):
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    return tmp_path


def test_cli_default_language_java(source_dir, tmp_path):
    output = tmp_path / "out.json"
    runner = CliRunner()
    with (
        patch("src.cli.setup_telemetry"),
        patch("src.cli.create_llm", return_value=MagicMock()),
        patch("src.cli.run_pipeline", new=AsyncMock(return_value=_make_final_output())),
    ):
        result = runner.invoke(analyze, ["--source", str(source_dir), "--output", str(output)])
    assert result.exit_code == 0, result.output


def test_cli_language_python(source_dir, tmp_path):
    output = tmp_path / "out.json"
    runner = CliRunner()
    with (
        patch("src.cli.setup_telemetry"),
        patch("src.cli.create_llm", return_value=MagicMock()),
        patch("src.cli.run_pipeline", new=AsyncMock(return_value=_make_final_output())),
        patch("src.cli.get_analyzer") as mock_get_analyzer,
    ):
        mock_get_analyzer.return_value = MagicMock(ext=".py")
        result = runner.invoke(
            analyze,
            ["--source", str(source_dir), "--output", str(output), "--language", "python"],
        )
    assert result.exit_code == 0, result.output
    mock_get_analyzer.assert_called_once_with(".py")


def test_cli_no_ext_option(source_dir, tmp_path):
    runner = CliRunner()
    with (
        patch("src.cli.setup_telemetry"),
        patch("src.cli.create_llm", return_value=MagicMock()),
        patch("src.cli.run_pipeline", new=AsyncMock(return_value=_make_final_output())),
    ):
        result = runner.invoke(analyze, ["--source", str(source_dir), "--ext", ".java"])
    assert result.exit_code != 0

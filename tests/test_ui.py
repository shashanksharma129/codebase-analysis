# tests/test_ui.py
import pytest

from ui import parse_github_url


def test_parse_simple_url():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_url_with_branch():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo/tree/develop")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "develop"


def test_parse_url_with_git_suffix():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo.git")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_url_with_trailing_slash():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo/")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_invalid_url_wrong_host():
    with pytest.raises(ValueError):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_invalid_url_not_a_url():
    with pytest.raises(ValueError):
        parse_github_url("not-a-url")

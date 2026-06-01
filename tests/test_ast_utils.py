import ast
from pathlib import Path
from src.ast_utils import (
    ASTSummary, FileSummary, MethodSummary,
    extract_ast_summary, render_ast_summary,
)


def _write(tmp_path, name, src):
    f = tmp_path / name
    f.write_text(src)
    return f


def test_extract_simple_class(tmp_path):
    f = _write(tmp_path, "svc.py", """
class UserService:
    def get_user(self, user_id: int) -> dict:
        pass
    def create_user(self, data: dict) -> dict:
        pass
""")
    summary, skipped = extract_ast_summary([f])
    assert skipped == []
    assert len(summary.files) == 1
    methods = summary.files[0].methods
    names = [m.name for m in methods]
    assert "get_user" in names
    assert "create_user" in names


def test_extract_async_method(tmp_path):
    f = _write(tmp_path, "handler.py", """
class Handler:
    async def handle(self, req) -> None:
        pass
""")
    summary, _ = extract_ast_summary([f])
    method = summary.files[0].methods[0]
    assert method.is_async is True
    assert "async def" in method.signature


def test_extract_fastapi_decorator(tmp_path):
    f = _write(tmp_path, "router.py", """
import fastapi
router = fastapi.APIRouter()

class UserRouter:
    @router.get("/users/{user_id}")
    async def get_user(self, user_id: int):
        pass
""")
    summary, _ = extract_ast_summary([f])
    method = summary.files[0].methods[0]
    assert any("/users/{user_id}" in d for d in method.decorators)


def test_detect_framework_fastapi(tmp_path):
    f = _write(tmp_path, "app.py", "from fastapi import FastAPI\napp = FastAPI()")
    summary, _ = extract_ast_summary([f])
    assert summary.detected_framework == "fastapi"
    assert summary.project_type == "web_service"


def test_detect_framework_flask(tmp_path):
    f = _write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)")
    summary, _ = extract_ast_summary([f])
    assert summary.detected_framework == "flask"
    assert summary.project_type == "web_service"


def test_detect_project_type_cli(tmp_path):
    f = _write(tmp_path, "cli.py", "import click\n@click.command()\ndef main(): pass")
    summary, _ = extract_ast_summary([f])
    assert summary.project_type == "cli"


def test_detect_project_type_data_science(tmp_path):
    f = _write(tmp_path, "model.py", "import pandas as pd\nimport numpy as np")
    summary, _ = extract_ast_summary([f])
    assert summary.project_type == "data_science"


def test_render_ast_summary(tmp_path):
    f = _write(tmp_path, "api.py", """
class UserAPI:
    async def get_user(self, user_id: int) -> dict:
        pass
""")
    summary, _ = extract_ast_summary([f])
    rendered = render_ast_summary(summary)
    assert "api.py" in rendered
    assert "UserAPI" in rendered
    assert "get_user" in rendered


def test_extract_syntax_error_file(tmp_path):
    good = _write(tmp_path, "good.py", "class A:\n    def f(self): pass\n")
    bad = _write(tmp_path, "bad.py", "def broken(:\n    pass\n")
    summary, skipped = extract_ast_summary([good, bad])
    assert any("bad.py" in s for s in skipped)
    assert len(summary.files) == 1


def test_has_async_detection(tmp_path):
    f = _write(tmp_path, "svc.py", "async def run(): pass")
    summary, _ = extract_ast_summary([f])
    assert summary.has_async is True


def test_class_inheritance_captured(tmp_path):
    f = _write(tmp_path, "router.py", "from fastapi import APIRouter\nclass UserRouter(APIRouter): pass")
    summary, _ = extract_ast_summary([f])
    assert any("UserRouter" in c for c in summary.files[0].classes)


def test_private_methods_excluded(tmp_path):
    f = _write(tmp_path, "svc.py", """
class MyService:
    def public_method(self): pass
    def _private_helper(self): pass
    def __init__(self): pass
    def __str__(self): pass

def module_public(): pass
def _module_private(): pass
""")
    summary, _ = extract_ast_summary([f])
    names = {m.name for m in summary.files[0].methods}
    assert "public_method" in names
    assert "__init__" in names
    assert "__str__" in names
    assert "_private_helper" not in names
    assert "module_public" in names
    assert "_module_private" not in names

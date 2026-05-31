import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_WEB_FRAMEWORKS = {
    "fastapi": {"fastapi"},
    "flask": {"flask"},
    "django": {"django"},
    "starlette": {"starlette"},
}
_CLI_IMPORTS = {"click"}
_DATA_IMPORTS = {"pandas", "numpy", "sklearn", "torch", "tensorflow", "scipy"}


@dataclass
class MethodSummary:
    name: str
    signature: str
    decorators: list[str]
    is_async: bool
    class_name: str | None
    docstring: str | None


@dataclass
class FileSummary:
    path: str
    imports: list[str]
    classes: list[str]
    methods: list[MethodSummary]
    docstring: str | None


@dataclass
class ASTSummary:
    files: list[FileSummary]
    detected_framework: str | None
    has_async: bool
    project_type: str


def _build_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args_str = ast.unparse(node.args)
    except Exception:
        args_str = "..."
    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args_str}){ret}"


def _decorator_str(node) -> str:
    try:
        return f"@{ast.unparse(node)}"
    except Exception:
        return "@<decorator>"


def _parse_file(path: Path) -> FileSummary:
    source = path.read_text(errors="ignore")
    tree = ast.parse(source, filename=str(path))

    imports: list[str] = []
    classes: list[str] = []
    methods: list[MethodSummary] = []
    module_docstring = ast.get_docstring(tree)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                imports.append(ast.unparse(node))
            except Exception:
                pass
        elif isinstance(node, ast.ClassDef):
            bases = ""
            if node.bases:
                try:
                    bases = f"({', '.join(ast.unparse(b) for b in node.bases)})"
                except Exception:
                    pass
            classes.append(f"{node.name}{bases}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(MethodSummary(
                        name=item.name,
                        signature=_build_signature(item),
                        decorators=[_decorator_str(d) for d in item.decorator_list],
                        is_async=isinstance(item, ast.AsyncFunctionDef),
                        class_name=node.name,
                        docstring=ast.get_docstring(item),
                    ))

    # module-level functions (direct children of module only)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(MethodSummary(
                name=node.name,
                signature=_build_signature(node),
                decorators=[_decorator_str(d) for d in node.decorator_list],
                is_async=isinstance(node, ast.AsyncFunctionDef),
                class_name=None,
                docstring=ast.get_docstring(node),
            ))

    return FileSummary(
        path=str(path),
        imports=imports,
        classes=classes,
        methods=methods,
        docstring=module_docstring,
    )


def _detect_framework_and_type(files: list[FileSummary]) -> tuple[str | None, str]:
    all_imports = " ".join(imp for f in files for imp in f.imports).lower()

    for framework, keywords in _WEB_FRAMEWORKS.items():
        if any(kw in all_imports for kw in keywords):
            return framework, "web_service"

    if any(kw in all_imports for kw in _CLI_IMPORTS):
        return None, "cli"

    if any(kw in all_imports for kw in _DATA_IMPORTS):
        return None, "data_science"

    return None, "library"


def extract_ast_summary(files: list[Path]) -> tuple[ASTSummary, list[str]]:
    parsed: list[FileSummary] = []
    skipped: list[str] = []

    for f in files:
        try:
            parsed.append(_parse_file(f))
        except SyntaxError:
            skipped.append(str(f))
            logger.warning("Skipped file with syntax error", extra={"path": str(f)})
        except OSError:
            skipped.append(str(f))
            logger.warning("Skipped unreadable file", extra={"path": str(f)})

    framework, project_type = _detect_framework_and_type(parsed)
    has_async = any(m.is_async for fs in parsed for m in fs.methods)

    return ASTSummary(
        files=parsed,
        detected_framework=framework,
        has_async=has_async,
        project_type=project_type,
    ), skipped


def render_ast_summary(summary: ASTSummary) -> str:
    lines: list[str] = []
    for fs in summary.files:
        name = Path(fs.path).name
        lines.append(f"=== {name} ===")
        if fs.docstring:
            lines.append(f'"""{fs.docstring}"""')

        by_class: dict[str | None, list[MethodSummary]] = {}
        for m in fs.methods:
            by_class.setdefault(m.class_name, []).append(m)

        for cls_entry in fs.classes:
            bare = cls_entry.split("(")[0]
            lines.append(f"Classes:\n  {cls_entry}:")
            for m in by_class.get(bare, []):
                for d in m.decorators:
                    lines.append(f"    {d}")
                lines.append(f"    {m.signature}")

        if None in by_class:
            lines.append("Module functions:")
            for m in by_class[None]:
                for d in m.decorators:
                    lines.append(f"  {d}")
                lines.append(f"  {m.signature}")

        lines.append("")

    meta = []
    if summary.detected_framework:
        meta.append(f"Framework: {summary.detected_framework}")
    meta.append(f"Project type: {summary.project_type}")
    if summary.has_async:
        meta.append("Uses async/await")
    if meta:
        lines.append("--- Metadata ---")
        lines.extend(meta)

    return "\n".join(lines)

import ast
from pathlib import Path


def test_training_package_isolated_from_pickle_task_router() -> None:
    package = Path("deepiri_zepgpu/training")
    forbidden = {
        "pickle",
        "cloudpickle",
        "deepiri_zepgpu.vpn.task_router",
        "deepiri_zepgpu.queue.tasks",
    }
    violations: list[str] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = {module, *(f"{module}.{alias.name}" for alias in node.names)}
            else:
                continue
            if names & forbidden:
                violations.append(f"{path}: {sorted(names & forbidden)}")
    assert violations == []


def test_binary_payload_modules_avoid_text_or_object_serialization() -> None:
    forbidden = {"base64", "json", "pickle", "cloudpickle"}
    for module_name in ("binary.py", "relay.py", "transport.py"):
        path = Path("deepiri_zepgpu/training") / module_name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        assert imported.isdisjoint(forbidden), f"{path} imports text/object serialization"


def test_training_package_imports_without_ml_dependencies() -> None:
    import deepiri_zepgpu.training as training

    assert training.TrainingRunConfig().schema_version == 1

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _import_call_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules = {"importlib"}
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    functions.add(alias.asname or alias.name)
    return modules, functions


def _literal_module(
    call: ast.Call, importlib_modules: set[str], import_module_functions: set[str],
) -> str | None:
    if not call.args or not isinstance(call.args[0], ast.Constant):
        return None
    value = call.args[0].value
    if not isinstance(value, str):
        return None
    if isinstance(call.func, ast.Name) and call.func.id == "__import__":
        return value
    if isinstance(call.func, ast.Name) and call.func.id in import_module_functions:
        return value
    if (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in importlib_modules
        and call.func.attr == "import_module"
    ):
        return value
    return None


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    importlib_modules, import_module_functions = _import_call_aliases(tree)
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        names.add(module)
        names.update(
            f"{module}.{alias.name}" if module else alias.name
            for alias in node.names
            if alias.name != "*"
        )
    names.update(
        module
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (module := _literal_module(
            node, importlib_modules, import_module_functions
        )) is not None
    )
    return names


def test_dynamic_import_detection_follows_importlib_aliases(tmp_path: Path) -> None:
    source = tmp_path / "dynamic.py"
    source.write_text(
        "from importlib import import_module\n"
        "from importlib import import_module as load\n"
        "import importlib as il\n"
        "import_module('parser')\n"
        "load('graph_dto.contract')\n"
        "il.import_module('metrics')\n"
        "il.import_module(variable)\n"
        "load(name='not-positional')\n",
        encoding="utf-8",
    )

    assert {"parser", "metrics", "graph_dto.contract"} <= _imports(source)
    assert "not-positional" not in _imports(source)


def test_import_guard_rejects_aliased_dynamic_imports_but_allows_nonliteral(
    tmp_path: Path,
) -> None:
    forbidden = tmp_path / "forbidden.py"
    forbidden.write_text(
        "import importlib as il\nil.import_module('metrics')\n", encoding="utf-8"
    )
    safe = tmp_path / "safe.py"
    safe.write_text(
        "from importlib import import_module\nimport_module(module_name)\n",
        encoding="utf-8",
    )

    try:
        _assert_no_imports([forbidden], {"metrics"})
    except AssertionError as error:
        assert "forbidden.py -> metrics" in str(error)
    else:
        raise AssertionError("aliased dynamic import was not rejected")
    _assert_no_imports([safe], {"metrics"})


def test_import_guard_rejects_qualified_cross_package_import_forms(
    tmp_path: Path,
) -> None:
    sources = {
        "static.py": "import app.algorithm.src.metrics\n",
        "dynamic.py": "import importlib\nimportlib.import_module('app.algorithm.src.metrics')\n",
        "from_alias.py": "from app.algorithm.src import metrics as measured\n",
    }
    paths = []
    for name, text in sources.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)

    for path in paths:
        try:
            _assert_no_imports([path], {"metrics"})
        except AssertionError as error:
            assert "app.algorithm.src.metrics" in str(error)
        else:
            raise AssertionError(f"qualified import was not rejected: {path.name}")


def test_import_guard_allows_unrelated_qualified_and_regular_imports(
    tmp_path: Path,
) -> None:
    source = tmp_path / "allowed.py"
    source.write_text(
        "import collections\n"
        "import vendor.metrics\n"
        "from app.algorithm.src import graph_dto\n"
        "from importlib import import_module\n"
        "import_module('vendor.metrics')\n",
        encoding="utf-8",
    )

    _assert_no_imports([source], {"metrics"})


def _assert_no_imports(paths: list[Path], forbidden: set[str]) -> None:
    violations = []
    for path in paths:
        for imported in _imports(path):
            root = imported.split(".", 1)[0]
            qualified_root = "app.algorithm.src."
            qualified = (
                imported[len(qualified_root):].split(".", 1)[0]
                if imported.startswith(qualified_root)
                else None
            )
            if root in forbidden or qualified in forbidden:
                try:
                    display = path.relative_to(ROOT)
                except ValueError:
                    display = path
                violations.append(f"{display} -> {imported}")
    assert not violations, "forbidden package imports:\n" + "\n".join(violations)


def _python_files(package: str, *, tests: bool) -> list[Path]:
    return [
        path for path in (ROOT / package).rglob("*.py")
        if path.name.startswith("test_") is tests
    ]


def test_production_package_import_boundaries() -> None:
    _assert_no_imports(_python_files("parser", tests=False), {"metrics", "gpt_work_dir"})
    _assert_no_imports(_python_files("metrics", tests=False), {"parser", "gpt_work_dir"})
    _assert_no_imports(_python_files("graph_dto", tests=False), {"parser", "metrics", "gpt_work_dir"})


def test_test_package_import_boundaries() -> None:
    _assert_no_imports(_python_files("parser", tests=True), {"metrics", "gpt_work_dir"})
    _assert_no_imports(_python_files("metrics", tests=True), {"parser", "gpt_work_dir"})
    _assert_no_imports(_python_files("graph_dto", tests=True), {"parser", "metrics", "gpt_work_dir"})


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1, f"expected one {name} in {path.relative_to(ROOT)}"
    return matches[0]


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        child.id for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def _literal_subscript_keys(node: ast.AST) -> set[str]:
    return {
        child.slice.value
        for child in ast.walk(node)
        if isinstance(child, ast.Subscript)
        and isinstance(child.slice, ast.Constant)
        and isinstance(child.slice.value, str)
    }


def _literal_mapping_keys(node: ast.AST) -> set[str]:
    keys = _literal_subscript_keys(node)
    keys.update(
        child.args[0].value
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "get"
        and child.args
        and isinstance(child.args[0], ast.Constant)
        and isinstance(child.args[0].value, str)
    )
    return keys


def test_literal_mapping_key_detection_covers_subscript_and_get() -> None:
    tree = ast.parse("graph['edges']; graph.get('edges'); graph.get(name)")
    assert _literal_mapping_keys(tree) == {"edges"}


def test_canonical_object_metrics_cannot_read_raw_edges() -> None:
    function = _function(
        ROOT / "metrics/logic/object_metrics.py",
        "calculate_canonical_object_metrics",
    )
    assert "edges" not in _literal_mapping_keys(function)


def test_known_legacy_resolution_markers_stay_in_compatibility_functions() -> None:
    call_graph = ROOT / "metrics/logic/call_graph.py"
    object_metrics = ROOT / "metrics/logic/object_metrics.py"
    identity = ROOT / "metrics/logic/identity.py"
    markers = {"suffix_index", "local_symbols", "by_short", "legacy_inheritance_depth"}
    allowed = {
        (call_graph, "calculate_call_graph_metrics"),
        (call_graph, "resolve"),
        (object_metrics, "calculate_object_metrics"),
        (object_metrics, "resolve"),
        (object_metrics, "legacy_inheritance_depth"),
        (identity, "legacy_file_id"),
        (identity, "semantic_module_name"),
        (identity, "effective_module_ids"),
        (identity, "graph_files"),
    }
    for path, name in allowed:
        _function(path, name)
    violations = []
    for path in (ROOT / "metrics").rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _loaded_names(node) & markers and (path, node.name) not in allowed:
                violations.append(f"{path.relative_to(ROOT)}:{node.name}")
    assert not violations, "legacy resolution escaped compatibility functions: " + ", ".join(violations)

    canonical_call = _function(call_graph, "_calculate_canonical_call_graph_metrics")
    canonical_objects = _function(object_metrics, "calculate_canonical_object_metrics")
    canonical_functions = (canonical_call, canonical_objects)
    legacy_helpers = {
        "legacy_file_id", "semantic_module_name", "effective_module_ids",
        "graph_files", "iter_legacy_calls", "legacy_inheritance_depth",
    }
    legacy_topology_keys = {
        "body", "semantic_target", "parent", "fields", "methods", "calls",
    }
    for function in canonical_functions:
        assert not (_loaded_names(function) & (markers | {"legacy_resolution"}))
        assert not (_called_names(function) & legacy_helpers)
        assert not (_literal_subscript_keys(function) & legacy_topology_keys)

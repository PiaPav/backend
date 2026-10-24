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
    _assert_no_imports(_python_files("views", tests=False), {"parser", "metrics", "gpt_work_dir"})


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


def _literal_root_mapping_keys(node: ast.AST, roots: set[str]) -> set[str]:
    keys = {
        child.slice.value
        for child in ast.walk(node)
        if isinstance(child, ast.Subscript)
        and isinstance(child.value, ast.Name)
        and child.value.id in roots
        and isinstance(child.slice, ast.Constant)
        and isinstance(child.slice.value, str)
    }
    keys.update(
        child.args[0].value
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id in roots
        and child.func.attr == "get"
        and child.args
        and isinstance(child.args[0], ast.Constant)
        and isinstance(child.args[0].value, str)
    )
    return keys


def test_literal_mapping_key_detection_covers_subscript_and_get() -> None:
    tree = ast.parse("graph['edges']; graph.get('edges'); graph.get(name)")
    assert _literal_mapping_keys(tree) == {"edges"}


def test_literal_root_mapping_key_detection_is_receiver_specific() -> None:
    tree = ast.parse(
        "graph['nodes']; graph.get('edges'); "
        "projection.get('callsites'); projection.parser_semantics_version"
    )
    assert _literal_root_mapping_keys(tree, {"graph"}) == {"nodes", "edges"}
    assert _literal_root_mapping_keys(tree, {"projection"}) == {"callsites"}


def test_canonical_consumers_cannot_read_projection_root_keys_from_raw_graph() -> None:
    forbidden = {
        "nodes", "edges", "callsites", "owner_structural_facts",
        "parser_semantics_version",
    }
    consumers = (
        (ROOT / "metrics/logic/complexity.py", "canonical_callable_metrics"),
        (ROOT / "metrics/logic/calculator.py", "_canonical_size"),
        (ROOT / "metrics/logic/calculator.py", "calculate_graph_metrics"),
        (ROOT / "metrics/logic/object_metrics.py", "_calculate_canonical_object_metrics"),
        (ROOT / "metrics/logic/call_graph.py", "_calculate_canonical_call_graph_metrics"),
    )
    violations = []
    for path, name in consumers:
        function = _function(path, name)
        keys = _literal_root_mapping_keys(function, {"graph"}) & forbidden
        if keys:
            violations.append(
                f"{path.relative_to(ROOT)}:{name} -> {', '.join(sorted(keys))}"
            )
    assert not violations, "canonical consumers read raw graph roots:\n" + "\n".join(violations)


def test_canonical_call_graph_and_complexity_calculators_are_projection_only() -> None:
    functions = (
        _function(
            ROOT / "metrics/logic/complexity.py",
            "canonical_callable_metrics",
        ),
        _function(
            ROOT / "metrics/logic/call_graph.py",
            "_calculate_canonical_call_graph_metrics",
        ),
    )
    for function in functions:
        positional = [*function.args.posonlyargs, *function.args.args]
        assert [argument.arg for argument in positional] == ["projection"]
        assert not function.args.defaults
        assert not function.args.kwonlyargs
        assert not function.args.vararg
        assert not function.args.kwarg


def test_internal_metrics_calculators_are_projection_only() -> None:
    calculators = (
        ("calculator.py", "_calculate_graph_metrics"),
        ("quality.py", "_callable_metrics"),
        ("quality.py", "_calculate_quality_metrics"),
        ("call_graph.py", "_calculate_call_graph_metrics"),
    )
    forbidden_helpers = {
        "from_graph", "graph_files", "legacy_file_id", "effective_module_ids",
    }
    forbidden_roots = {
        "body", "nodes", "edges", "callsites", "import_references",
        "owner_structural_facts", "parser_semantics_version",
    }
    for filename, name in calculators:
        function = _function(ROOT / "metrics/logic" / filename, name)
        positional = [*function.args.posonlyargs, *function.args.args]
        assert positional and positional[0].arg == "projection"
        assert "graph" not in {argument.arg for argument in positional}
        assert not (_called_names(function) & forbidden_helpers)
        assert not (_literal_root_mapping_keys(function, {"graph"}) & forbidden_roots)


def test_aggregate_and_public_gateway_signatures_are_canonical_only() -> None:
    aggregate = _function(ROOT / "metrics/logic/calculator.py", "calculate_graph_metrics")
    internal = _function(ROOT / "metrics/logic/calculator.py", "_calculate_graph_metrics")
    assert [argument.arg for argument in aggregate.args.args] == ["graph"]
    assert not aggregate.args.kwonlyargs
    assert [argument.arg for argument in internal.args.args] == ["projection"]
    assert not internal.args.kwonlyargs

    gateways = (
        ("call_graph.py", "calculate_call_graph_metrics"),
        ("object_metrics.py", "calculate_object_metrics"),
        ("object_metrics.py", "calculate_canonical_object_metrics"),
        ("quality.py", "callable_metrics"),
        ("quality.py", "calculate_quality_metrics"),
    )
    for filename, name in gateways:
        function = _function(ROOT / "metrics/logic" / filename, name)
        assert [argument.arg for argument in function.args.args] == ["graph"]
        assert [argument.arg for argument in function.args.kwonlyargs] == ["projection"]
        assert not function.args.vararg
        assert not function.args.kwarg


def test_canonical_object_metrics_cannot_read_raw_edges() -> None:
    function = _function(
        ROOT / "metrics/logic/object_metrics.py",
        "_calculate_canonical_object_metrics",
    )
    assert "edges" not in _literal_mapping_keys(function)


def test_canonical_object_metrics_calculator_is_projection_only() -> None:
    function = _function(
        ROOT / "metrics/logic/object_metrics.py",
        "_calculate_canonical_object_metrics",
    )
    positional = [*function.args.posonlyargs, *function.args.args]
    assert [argument.arg for argument in positional] == ["projection"]
    assert not function.args.defaults
    assert [argument.arg for argument in function.args.kwonlyargs] == [
        "wmc_by_class_id"
    ]
    assert len(function.args.kw_defaults) == 1
    assert isinstance(function.args.kw_defaults[0], ast.Constant)
    assert function.args.kw_defaults[0].value is None
    assert not function.args.vararg
    assert not function.args.kwarg


def test_architecture_metrics_is_projection_only_and_avoids_raw_helpers() -> None:
    path = ROOT / "metrics/logic/architecture.py"
    function = _function(path, "calculate_architecture_metrics")
    assert [argument.arg for argument in function.args.args] == ["projection"]
    assert not function.args.kwonlyargs
    assert not function.args.vararg
    assert not function.args.kwarg
    assert not (_called_names(function) & {
        "effective_module_ids", "graph_files", "legacy_file_id",
        "semantic_module_name", "_package", "_canonical_package",
    })


def test_production_metrics_contains_no_legacy_resolution_markers() -> None:
    call_graph = ROOT / "metrics/logic/call_graph.py"
    object_metrics = ROOT / "metrics/logic/object_metrics.py"
    markers = {
        "legacy_files", "effective_module_ids", "iter_legacy_calls",
        "legacy_file_id", "semantic_target", "suffix_index", "local_symbols",
        "by_short", "legacy_inheritance_depth", "canonical_mode",
        "canonical_objects", "canonical_calls", "legacy_resolution",
    }
    violations = []
    for path in (ROOT / "metrics").rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        identifiers = _loaded_names(tree) | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        identifiers.update(
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        found = identifiers & markers
        if found:
            violations.append(
                f"{path.relative_to(ROOT)} -> {', '.join(sorted(found))}"
            )
    assert not violations, "legacy resolution escaped compatibility functions: " + ", ".join(violations)

    canonical_call = _function(call_graph, "_calculate_canonical_call_graph_metrics")
    canonical_objects = _function(object_metrics, "_calculate_canonical_object_metrics")
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


def test_production_metrics_never_reads_body_or_imports_identity_module() -> None:
    violations = []
    for path in (ROOT / "metrics").rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if "body" in _literal_mapping_keys(tree):
            violations.append(f"{path.relative_to(ROOT)} reads body")
        imports = _imports(path)
        if any(
            imported == "metrics.logic.identity"
            or imported.endswith(".identity")
            or imported == "identity"
            for imported in imports
        ):
            violations.append(f"{path.relative_to(ROOT)} imports identity")
    assert not violations, "forbidden Metrics dependencies:\n" + "\n".join(violations)

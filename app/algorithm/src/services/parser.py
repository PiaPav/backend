# самая актуальная версия
import ast
import json
import os
import re
import tomllib
from typing import Dict, List, Any, Optional, Union, AsyncIterator, Tuple


class Parser:
    @staticmethod
    def get_name(node: ast.AST) -> str:
        """Получить полное имя объекта (для вызовов и атрибутов)"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{Parser.get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return Parser.get_name(node.func)
        return ""

    @staticmethod
    def get_decorators(decorator_list: List[ast.AST]) -> List[Dict[str, Any]]:
        """Собрать информацию о декораторах"""
        decorators = []
        for dec in decorator_list:
            dec_info = {"name": Parser.get_name(dec), "args": []}
            if isinstance(dec, ast.Call):
                dec_info["name"] = Parser.get_name(dec.func)
                dec_info["args"] = [ast.unparse(arg) for arg in dec.args]
            decorators.append(dec_info)
        return decorators

    # @staticmethod
    # def get_calls(node: ast.AST) -> List[str]:
    #     """Собрать все вызовы функций внутри узла"""
    #     calls = []
    #     for child in ast.walk(node):
    #         if isinstance(child, ast.Call):
    #             calls.append(ParseService.get_name(child.func))
    #     return calls

    @staticmethod
    def parse_assignments(node: ast.AST) -> List[Dict[str, Any]]:
        """Собрать глобальные присваивания"""
        assigns = []
        for child in node.body:
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    assigns.append({
                        "target": ast.unparse(target),
                        "value": ast.unparse(child.value),
                        "type": type(child.value).__name__
                    })
        return assigns

    @staticmethod
    def parse_imports(node: ast.AST) -> List[Dict[str, Any]]:
        """Собрать импорты"""
        imports = []
        for child in node.body:
            if isinstance(child, ast.Import):
                for alias in child.names:
                    imports.append({
                        "type": "import",
                        "module": alias.name,
                        "alias": alias.asname,
                    })
            elif isinstance(child, ast.ImportFrom):
                for alias in child.names:
                    imports.append({
                        "type": "from",
                        "module": child.module,
                        "name": alias.name,
                        "alias": alias.asname,
                        "level": child.level,
                    })
        return imports


class EnhancedFunctionParser:
    """Улучшенный парсер функций с интеграцией поиска эндпоинтов"""

    @staticmethod
    def get_call_name(node: ast.AST) -> Optional[str]:
        """Рекурсивно восстанавливает имя вызова (например, log.info, service.get_project_by_id)."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value_name = EnhancedFunctionParser.get_call_name(node.value)
            return f"{value_name}.{node.attr}" if value_name else node.attr
        return None

    @staticmethod
    def parse_function(node: Union[ast.FunctionDef, ast.AsyncFunctionDef], file_path: str,
                       class_name: Optional[str] = None) -> Dict[str, Any]:
        """Извлекает данные о функции и всех вызовах внутри с улучшенной информацией"""
        calls = []

        class CallVisitor(ast.NodeVisitor):
            def visit_Call(self, call_node):
                func_name = EnhancedFunctionParser.get_call_name(call_node.func)
                if func_name:
                    calls.append(func_name)
                self.generic_visit(call_node)

        CallVisitor().visit(node)

        # Получаем аргументы и их аннотации
        args = []
        arg_types = {}
        for arg in node.args.args:
            args.append(arg.arg)
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    arg_types[arg.arg] = arg.annotation.id
                elif isinstance(arg.annotation, ast.Subscript) and isinstance(arg.annotation.value, ast.Name):
                    arg_types[arg.arg] = arg.annotation.value.id

        # Получаем информацию о декораторах
        decorators = Parser.get_decorators(node.decorator_list)

        # Определяем тип функции
        if class_name:
            _type = "method"
        elif isinstance(node, ast.AsyncFunctionDef):
            _type = "async_function"
        else:
            _type = "function"

        # Получаем возвращаемое значение
        returns = ast.unparse(node.returns) if node.returns else None

        func_info = {
            "_type": _type,
            "name": node.name,
            "file": file_path,
            "args": args,
            "arg_types": arg_types,
            "returns": returns,
            "decorators": decorators,
            "calls": calls,
            "is_endpoint": False,
            "endpoint_info": None
        }

        if class_name:
            func_info["class"] = class_name

        # Проверяем, является ли функция эндпоинтом
        func_info = EnhancedFunctionParser._detect_endpoint(func_info)

        return func_info

    @staticmethod
    def _detect_endpoint(func_info: Dict[str, Any]) -> Dict[str, Any]:
        """Определяет, является ли функция эндпоинтом и собирает информацию о нем"""
        http_methods = {"get", "post", "put", "patch", "delete"}

        for decorator in func_info.get("decorators", []):
            name = decorator.get("name", "")
            parts = name.split(".")
            if len(parts) == 2:
                obj, method = parts
                if method.lower() in http_methods:
                    func_info["is_endpoint"] = True
                    func_info["endpoint_info"] = {
                        "decorator": {
                            "object": obj,
                            "method": method.lower(),
                            "args": decorator.get("args", [])
                        },
                        "path": decorator.get("args", [""])[0].strip('"\'') if decorator.get("args") else ""
                    }
                    # print("-+"*100)
                    # print(json.dumps(func_info, indent=2))
                    # print("-+" * 100)
                    break

        return func_info

    @staticmethod
    def parse_python_file(file_path: str) -> Dict[str, Dict[str, Any]]:
        """Возвращает все функции и методы из файла с улучшенной информацией"""
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)

        funcs = {}

        # Собираем информацию о присваиваниях и импортах для контекста
        assignments = Parser.parse_assignments(tree)
        imports = Parser.parse_imports(tree)

        # Находим роутеры для построения полных путей эндпоинтов
        routers = {}
        for a in assignments:
            if a["type"] == "Call" and re.match(r"APIRouter", a["value"]):
                prefix_match = re.search(r"prefix\s*=\s*['\"]([^'\"]+)['\"]", a["value"])
                prefix = prefix_match.group(1) if prefix_match else ""
                routers[a["target"]] = prefix

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = EnhancedFunctionParser.parse_function(node, file_path)
                # Обновляем информацию об эндпоинте с учетом роутеров
                func = EnhancedFunctionParser._enhance_endpoint_info(func, routers)
                funcs[func["name"]] = func
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func = EnhancedFunctionParser.parse_function(sub, file_path, class_name=node.name)
                        # Обновляем информацию об эндпоинте с учетом роутеров
                        func = EnhancedFunctionParser._enhance_endpoint_info(func, routers)
                        funcs[f"{node.name}.{func['name']}"] = func

        return funcs

    @staticmethod
    def _enhance_endpoint_info(func_info: Dict[str, Any], routers: Dict[str, str]) -> Dict[str, Any]:
        """Дополняет информацию об эндпоинте префиксом роутера"""
        if func_info.get("is_endpoint") and func_info["endpoint_info"]:
            endpoint_info = func_info["endpoint_info"]
            router_obj = endpoint_info["decorator"]["object"]
            prefix = routers.get(router_obj, "")
            path = endpoint_info.get("path", "")

            # Обновляем полный путь
            endpoint_info["full_path"] = f"{prefix}{path}"

            # Извлекаем response_model если есть
            response_model = None
            for arg in endpoint_info["decorator"].get("args", []):
                if "response_model" in arg:
                    match = re.search(r"response_model\s*=\s*([A-Za-z_][A-Za-z0-9_\.]*)", arg)
                    if match:
                        response_model = match.group(1)

            if not response_model:
                response_model = func_info.get("returns")

            endpoint_info["response_model"] = response_model

        return func_info

    @staticmethod
    def collect_project_functions(project_path: str) -> Dict[str, Dict[str, Any]]:
        """Собирает все функции проекта (ключ — имя функции или метода)"""
        all_functions = {}
        for root, _, files in os.walk(project_path):
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        funcs = EnhancedFunctionParser.parse_python_file(file_path)
                        all_functions.update(funcs)
                    except Exception as e:
                        print(f"Ошибка при парсинге файла {file_path}: {e}")
        return all_functions

    @staticmethod
    def map_call_to_function(call: str, func_info: Dict[str, Any], all_funcs: Dict[str, Dict[str, Any]]) -> Optional[
        Dict[str, Any]]:
        """Сопоставляет вызов с функцией"""
        if "." not in call:
            return all_funcs.get(call)

        obj, method = call.split(".", 1)
        obj_type = func_info.get("arg_types", {}).get(obj)
        if obj_type:
            candidate_name = f"{obj_type}.{method}"
            if candidate_name in all_funcs:
                return all_funcs[candidate_name]

        # fallback: ищем метод по имени
        for f_name, f_info in all_funcs.items():
            if f_info.get("name") == method:
                return f_info
        return None

    @staticmethod
    async def build_call_graph(project_path: str) -> AsyncIterator[Tuple[str, Any]]:
        """
        Асинхронный итератор, который yield-ит части графа
        """

        # ⚠gather functions (синхронный код, оставляем как есть)
        all_funcs = EnhancedFunctionParser.collect_project_functions(project_path)

        for func_name, func_data in all_funcs.items():
            # print(f"! {func_name}")
            # print(f"? {func_data}")

            children: List[str] = []

            for call in func_data["calls"]:
                # print(f"/ {call}")
                target_func = EnhancedFunctionParser.map_call_to_function(
                    call, func_data, all_funcs
                )
                # print(f"! ", target_func)
                # print(f"? ", call)

                # имя вызванной функции (разрешённое или как есть)
                resolved_name = (
                    f"{os.path.splitext(os.path.basename(target_func['file']))[0]}/{target_func['class']}.{target_func['name']}"
                    if target_func and "class" in target_func and "file" in target_func
                    else f"{os.path.splitext(os.path.basename(func_data['file']))[0]}/{call}"
                )

                children.append(resolved_name)

            # ✅ отдаём кусок графа:
            #    parent → children
            yield func_name, children

            # при большом проекте даём петле event loop выполнить другие задачи
            # await asyncio.sleep(0)  # микро-уступка планировщику

    @staticmethod
    def build_call_graph2(project_path: str) -> List[Dict[str, Any]]:
        """Формирует список связности графа: каждая функция + вызовы с указанием файла"""
        all_funcs = EnhancedFunctionParser.collect_project_functions(project_path)
        results: List[Dict[str, Any]] = []

        for func_name, func_data in all_funcs.items():
            func_entry = {
                "name": func_name,
                "file": func_data["file"],
                "args": func_data["args"],
                "_type": func_data["_type"],
                "returns": func_data.get("returns"),
                "decorators": func_data.get("decorators", []),
                "is_endpoint": func_data.get("is_endpoint", False),
                "endpoint_info": func_data.get("endpoint_info"),
                "calls": []
            }

            for call in func_data["calls"]:
                target_func = EnhancedFunctionParser.map_call_to_function(call, func_data, all_funcs)
                call_info = {
                    "name": call,
                    "resolved_name": f"{target_func['class']}.{target_func['name']}" if target_func and "class" in target_func else call,
                    "file": target_func["file"] if target_func else "external",
                    "is_endpoint": target_func.get("is_endpoint", False) if target_func else False
                }
                func_entry["calls"].append(call_info)

            results.append(func_entry)

        return results

    @staticmethod
    def extract_endpoints(project_path: str) -> List[Dict[str, Any]]:
        """Извлекает все эндпоинты из проекта"""
        all_funcs = EnhancedFunctionParser.collect_project_functions(project_path)
        endpoints = []

        for func_name, func_data in all_funcs.items():
            if func_data.get("is_endpoint"):
                endpoint_info = func_data["endpoint_info"]
                endpoints.append({
                    "function": func_name,
                    "file": func_data["file"],
                    "method": endpoint_info["decorator"]["method"].upper(),
                    "path": endpoint_info["full_path"],
                    "args": func_data["args"],
                    "response_model": endpoint_info.get("response_model"),
                    "calls": func_data["calls"],
                    "decorators": func_data.get("decorators", [])
                })

        return endpoints

    @staticmethod
    def parse_requirements(req_path: str):
        """
        Возвращает список имён пакетов из requirements.txt
        """
        deps = []
        with open(req_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Пропускаем комментарии и пустые строки
                if not line or line.startswith("#"):
                    continue
                # Отрезаем всё после версии (==, >=, <=, ~=, >, <)
                name = re.split(r"[=<>~!]", line)[0].strip()
                if name:
                    deps.append(name)
        return deps

    @staticmethod
    def parse_pyproject(pyproject_path: str):
        """
        Возвращает список имён пакетов из pyproject.toml
        (поддерживает [project] и [tool.poetry.dependencies])
        """
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        deps = []

        # --- PEP 621 style ---
        project = data.get("project", {})
        if "dependencies" in project:
            for dep in project["dependencies"]:
                name = re.split(r"[=<>!~\[\s]", dep, maxsplit=1)[0].strip()
                if name:
                    deps.append(name)

        # --- Poetry style ---
        poetry = data.get("tool", {}).get("poetry", {})
        if "dependencies" in poetry:
            for name in poetry["dependencies"]:
                if name.lower() != "python":
                    deps.append(name)

        return sorted(set(deps))

    @staticmethod
    def find_dependencies_files(root_dir: str) -> list:
        """
        Ищет все Файлы зависимостей
        """
        special_files = []

        for dirpath, dirnames, filenames in os.walk(root_dir):

            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if filename in ("pyproject.toml", "requirements.txt"):
                    special_files.append(filepath)

        return special_files

    @staticmethod
    def get_dependencies(path: str) -> dict:
        """Возвращает список зависимостей"""
        files = EnhancedFunctionParser.find_dependencies_files(path)

        result = {}

        for file in files:
            if file[-4::] == ".txt":
                result[os.path.basename(file)] = EnhancedFunctionParser.parse_requirements(file)
            elif file[-5::] == ".toml":
                result[os.path.basename(file)] = EnhancedFunctionParser.parse_pyproject(file)

        return result


# Пример использования
# if __name__ == "__main__":
#     project_path = r"C:\Users\Red0c\PycharmProjects\PiaPav\backend\app\core\src"
#
#     dependencies = EnhancedFunctionParser.get_dependencies(r"C:\Users\Red0c\PycharmProjects\PiaPav\backend\app\core")
#     print(dependencies)
#
#     # Получаем полный граф вызовов
#     call_graph = EnhancedFunctionParser.build_call_graph2(project_path)
#     print("Граф вызовов построен. Функций:", len(call_graph))
#
#     # Получаем только эндпоинты
#     endpoints = EnhancedFunctionParser.extract_endpoints(project_path)
#     print("Найдено эндпоинтов:", len(endpoints))
#
#     # Выводим информацию об эндпоинтах
#     for endpoint in endpoints:
#         print(f"{endpoint['method']} {endpoint['path']} -> {endpoint['function']}")
#     print(json.dumps(call_graph, indent=2))
#     from visual import visual
#
#     visual(call_graph)

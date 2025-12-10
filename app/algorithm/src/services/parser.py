# самая актуальная версия
import ast
import json
import os
import re
import tomllib
from typing import Dict, List, Any, Optional, Union, AsyncIterator, Tuple

from services.manage.object_manager import object_manager


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

    HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

    @staticmethod
    def get_call_name(node: ast.AST) -> Optional[str]:
        """Быстрое восстановление полного имени вызова"""
        parts = []
        while True:
            if isinstance(node, ast.Name):
                parts.append(node.id)
                break
            elif isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            elif isinstance(node, ast.Call):
                node = node.func
            else:
                break
        return ".".join(reversed(parts)) if parts else None

    @staticmethod
    def parse_function(node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
                       file_path: str,
                       class_name: Optional[str] = None) -> Dict[str, Any]:
        """Парсит функцию и собирает вызовы и декораторы"""
        calls = [EnhancedFunctionParser.get_call_name(n.func)
                 for n in ast.walk(node)
                 if isinstance(n, ast.Call) and EnhancedFunctionParser.get_call_name(n.func)]

        args = [arg.arg for arg in node.args.args]
        arg_types = {arg.arg: arg.annotation.id
                     for arg in node.args.args if isinstance(arg.annotation, ast.Name)}

        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                name = EnhancedFunctionParser.get_call_name(dec.func)
                dec_info = {
                    "name": name,
                    "args": [ast.unparse(arg) for arg in dec.args],
                    "raw_args": dec.args,  # <--- добавлено
                    "raw_keywords": dec.keywords,  # <--- добавлено
                }
            else:
                name = EnhancedFunctionParser.get_call_name(dec)
                dec_info = {
                    "name": name,
                    "args": [],
                    "raw_args": [],
                    "raw_keywords": [],
                }

            decorators.append(dec_info)

        _type = "method" if class_name else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
        returns = node.returns.id if isinstance(node.returns, ast.Name) else None

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

        # Сразу проверяем эндпоинт
        return EnhancedFunctionParser._detect_endpoint(func_info)

    @staticmethod
    def _detect_endpoint(func_info: Dict[str, Any]) -> Dict[str, Any]:

        for dec in func_info["decorators"]:
            name = dec.get("name")
            if not name:
                continue

            parts = name.split(".")
            if len(parts) != 2:
                continue

            obj, method = parts
            method_lower = method.lower()

            # Проверяем HTTP-метод
            if method_lower not in EnhancedFunctionParser.HTTP_METHODS:
                continue

            # ---- ИЩЕМ ПУТЬ ----
            # Путь в FastAPI — это СТРОКА (ast.Constant со строкой)
            path = ""

            raw_args = dec.get("raw_args", [])
            for arg in raw_args:
                # позиционный аргумент — строка → это path
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    path = arg.value
                    break

            # ---- ИЩЕМ response_model ----
            response_model = None
            raw_keywords = dec.get("raw_keywords", [])

            for kw in raw_keywords:
                if kw.arg == "response_model":
                    if isinstance(kw.value, ast.Name):
                        response_model = kw.value.id
                    elif isinstance(kw.value, ast.Attribute):
                        response_model = EnhancedFunctionParser.get_call_name(kw.value)
                    break

            # Если response_model не найден — используем return type
            if not response_model:
                returns = func_info.get("returns")
                if returns:
                    response_model = returns

            # ---- СОХРАНЯЕМ ----
            func_info["is_endpoint"] = True
            func_info["endpoint_info"] = {
                "decorator": {
                    "object": obj,
                    "method": method_lower,
                    "args": dec.get("args", []),
                },
                "path": path,
                "full_path": path,  # префиксы добавятся позднее
                "response_model": response_model,
            }

            break

        return func_info

    @staticmethod
    async def parse_python_file_s3(file_path: str) -> Dict[str, Dict[str, Any]]:
        """Парсит .py файл из S3"""
        code = await object_manager.repo.read(file_path)
        tree = ast.parse(code, filename=file_path)
        funcs = {}

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = EnhancedFunctionParser.parse_function(node, file_path)
                funcs[func["name"]] = func
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func = EnhancedFunctionParser.parse_function(sub, file_path, class_name=node.name)
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
    async def collect_project_functions_s3(prefix: str) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
        """Асинхронный генератор функций проекта по мере чтения файлов из S3"""
        keys = await object_manager.repo.get_filenames(prefix)
        py_files = [k for k in keys if k.endswith(".py")]

        for file_key in py_files:
            try:
                funcs = await EnhancedFunctionParser.parse_python_file_s3(file_key)
                for func_name, func_data in funcs.items():
                    yield func_name, func_data
            except Exception as e:
                print(f"Ошибка при парсинге S3 файла {file_key}: {e}")

    @staticmethod
    def build_functions_index(funcs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Быстрый индекс функций для поиска вызовов"""
        index = {}
        for f_name, f_info in funcs.items():
            index[f_name] = f_info
            cls_name = f_info.get("class")
            if cls_name:
                index[f"{cls_name}.{f_info['name']}"] = f_info
        return index

    @staticmethod
    def map_call_to_function(call: str, func_info: Dict[str, Any], all_funcs_index: Dict[str, Dict[str, Any]]):
        """Быстрый поиск функции через индекс"""
        if call in all_funcs_index:
            return all_funcs_index[call]
        obj, _, method = call.partition(".")
        obj_type = func_info.get("arg_types", {}).get(obj)
        if obj_type:
            return all_funcs_index.get(f"{obj_type}.{method}")
        return None

    @staticmethod
    async def build_call_graph_s3(prefix: str) -> AsyncIterator[Tuple[str, List[str]]]:
        """Асинхронный генератор графа вызовов по мере парсинга"""
        all_funcs: Dict[str, Dict[str, Any]] = {}
        async for func_name, func_data in EnhancedFunctionParser.collect_project_functions_s3(prefix):
            all_funcs[func_name] = func_data
            all_funcs_index = EnhancedFunctionParser.build_functions_index(all_funcs)

            children: List[str] = []
            for call in func_data["calls"]:
                target_func = EnhancedFunctionParser.map_call_to_function(call, func_data, all_funcs_index)
                resolved_name = (
                    f"{target_func['file']}/{target_func['class']}.{target_func['name']}"
                    if target_func and "class" in target_func and "file" in target_func
                    else f"{func_data['file']}/{call}"
                )
                children.append(resolved_name)

            yield func_name, children

    @staticmethod
    async def build_call_graph2(project_path: str) -> List[Dict[str, Any]]:
        """Формирует список связности графа: каждая функция + вызовы с указанием файла"""
        all_funcs = await EnhancedFunctionParser.collect_project_functions_s3(project_path)
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
    async def extract_endpoints(prefix: str) -> List[Dict[str, Any]]:
        """Собирает все эндпоинты проекта за один проход"""
        endpoints = []
        keys = await object_manager.repo.get_filenames(prefix)
        py_files = [k for k in keys if k.endswith(".py")]

        for file_key in py_files:
            try:
                funcs = await EnhancedFunctionParser.parse_python_file_s3(file_key)
                for func_name, func_data in funcs.items():
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
            except Exception as e:
                print(f"Ошибка при парсинге {file_key}: {e}")
        return endpoints

    @staticmethod
    async def parse_requirements_s3(file_key: str) -> List[str]:
        """Возвращает список имён пакетов из requirements.txt, файл из S3"""
        deps = []
        async for line in object_manager.repo.stream_read(file_key, decode="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[=<>~!]", line)[0].strip()
            if name:
                deps.append(name)
        return deps

    @staticmethod
    async def parse_pyproject_s3(file_key: str) -> List[str]:
        """Возвращает список имён пакетов из pyproject.toml, файл из S3"""
        import io
        import tomllib

        # собираем все чанки в BytesIO, так как tomllib читает бинарные данные
        chunks = []
        async for chunk in object_manager.repo.stream_read(file_key):
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunks.append(chunk)
        f = io.BytesIO(b"".join(chunks))
        data = tomllib.load(f)

        deps = []

        # --- PEP 621 style ---
        project = data.get("project", {})
        for dep in project.get("dependencies", []):
            name = re.split(r"[=<>!~\[\s]", dep, maxsplit=1)[0].strip()
            if name:
                deps.append(name)

        # --- Poetry style ---
        poetry = data.get("tool", {}).get("poetry", {})
        for name in poetry.get("dependencies", {}):
            if name.lower() != "python":
                deps.append(name)

        return sorted(set(deps))

    @staticmethod
    async def find_dependencies_files_s3(prefix: str) -> List[str]:
        """Ищет все файлы зависимостей в S3 по префиксу"""
        all_keys = await object_manager.repo.get_filenames(prefix)
        # print(all_keys)
        return [k for k in all_keys if k.endswith(("requirements.txt", "pyproject.toml"))]

    @staticmethod
    async def get_dependencies_s3(prefix: str) -> Dict[str, List[str]]:
        """Возвращает список зависимостей из S3"""
        result = {}
        files = await EnhancedFunctionParser.find_dependencies_files_s3(prefix)

        for file_key in files:
            try:
                if file_key.endswith(".txt"):
                    deps = await EnhancedFunctionParser.parse_requirements_s3(file_key)
                    result[os.path.basename(file_key)] = deps
                elif file_key.endswith(".toml"):
                    deps = await EnhancedFunctionParser.parse_pyproject_s3(file_key)
                    result[os.path.basename(file_key)] = deps
            except Exception as e:
                print(f"Ошибка при чтении зависимостей из {file_key}: {e}")

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

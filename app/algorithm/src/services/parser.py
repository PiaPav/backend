# самая актуальная версия
import ast
import os
import re
from typing import Dict, List, Any, Optional, Union, AsyncIterator, Tuple

from services.manage.object_manager import object_manager


class Parser:
    """Улучшенный парсер"""

    HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

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
    def parse_router_defs(tree: ast.Module) -> Dict[str, str]:
        """
        Ищет объявления:
        router = APIRouter(prefix="/xxx")
        app = FastAPI(root_path="/xxx")
        """
        routers = {}

        for node in tree.body:
            # Ищем присваивания: router = APIRouter(...)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call_name = Parser.get_call_name(node.value.func)

                # Сохраняем имя переменной
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue

                var_name = node.targets[0].id

                # APIRouter
                if call_name.endswith("APIRouter"):
                    prefix = ""
                    for kw in node.value.keywords:
                        if kw.arg == "prefix":
                            prefix = ast.literal_eval(kw.value)  # гарантированно str
                    routers[var_name] = prefix

                # FastAPI
                if call_name.endswith("FastAPI"):
                    prefix = ""
                    for kw in node.value.keywords:
                        if kw.arg in ("root_path", "prefix"):
                            prefix = ast.literal_eval(kw.value)
                    routers[var_name] = prefix

        return routers

    @staticmethod
    def parse_function(node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
                       file_path: str,
                       class_name: Optional[str] = None) -> Dict[str, Any]:
        """Парсит функцию и собирает вызовы и декораторы"""
        calls = [Parser.get_call_name(n.func)
                 for n in ast.walk(node)
                 if isinstance(n, ast.Call) and Parser.get_call_name(n.func)]

        args = [arg.arg for arg in node.args.args]
        arg_types = {arg.arg: arg.annotation.id
                     for arg in node.args.args if isinstance(arg.annotation, ast.Name)}

        decorators = []
        for dec in node.decorator_list:
            name = Parser.get_call_name(
                dec.func if isinstance(dec, ast.Call) else dec
            )

            dec_args = []
            path = ""

            if isinstance(dec, ast.Call):

                # --- позиционные аргументы ---
                for arg in dec.args:
                    # path должен быть строкой
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        path = arg.value
                    else:
                        dec_args.append(ast.unparse(arg))

                # --- именованные аргументы ---
                for kw in dec.keywords:
                    if kw.arg == "response_model":
                        dec_args.append(f"response_model={ast.unparse(kw.value)}")
                    else:
                        dec_args.append(ast.unparse(kw.value))

            decorators.append({
                "name": name,
                "args": dec_args,
                "path": path
            })

            # СФОРМИРОВАТЬ И ВЕРНУТЬ ИНФО О ФУНКЦИИ
            func_info = {
                "name": node.name,
                "file": file_path,
                "class": class_name,
                "args": args,
                "arg_types": arg_types,
                "decorators": decorators,
                "calls": calls,
                "is_endpoint": False,
                "endpoint_info": None,
                "_type": "async" if isinstance(node, ast.AsyncFunctionDef) else "sync",
                "returns": ast.unparse(node.returns) if node.returns else None,
            }

            func_info = Parser._detect_endpoint(func_info)

            return func_info

    @staticmethod
    def _detect_endpoint(func_info: Dict[str, Any]) -> Dict[str, Any]:
        for dec in func_info["decorators"]:
            if not dec["name"]:
                continue

            parts = dec["name"].split(".")
            if len(parts) == 2:
                obj, method = parts
                if method.lower() in Parser.HTTP_METHODS:
                    func_info["is_endpoint"] = True

                    func_info["endpoint_info"] = {
                        "decorator": {
                            "object": obj,
                            "method": method.lower(),
                            "args": dec["args"]
                        },
                        "path": dec.get("path", "") or "",
                        "full_path": dec.get("path", "") or "",
                    }
                    break
        return func_info

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
    async def parse_python_file_s3(file_path: str) -> Dict[str, Dict[str, Any]]:
        code = await object_manager.repo.read(file_path)
        tree = ast.parse(code, filename=file_path)

        # --- собираем роутеры/APIRouter/приложения ---
        routers = Parser.parse_router_defs(tree)

        funcs = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = Parser.parse_function(node, file_path)
                if func is None:
                    continue
                func = Parser._enhance_endpoint_info(func, routers)
                funcs[func["name"]] = func

            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func = Parser.parse_function(sub, file_path, class_name=node.name)
                        if func is None:
                            continue
                        func = Parser._enhance_endpoint_info(func, routers)
                        funcs[f"{node.name}.{func['name']}"] = func

        return funcs

    @staticmethod
    async def collect_project_functions_s3(prefix: str) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
        """Асинхронный генератор функций проекта по мере чтения файлов из S3"""
        keys = await object_manager.repo.get_filenames(prefix)
        py_files = [k for k in keys if k.endswith(".py")]

        for file_key in py_files:
            try:
                funcs = await Parser.parse_python_file_s3(file_key)
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
        async for func_name, func_data in Parser.collect_project_functions_s3(prefix):
            all_funcs[func_name] = func_data
            all_funcs_index = Parser.build_functions_index(all_funcs)

            children: List[str] = []
            for call in func_data["calls"]:
                target_func = Parser.map_call_to_function(call, func_data, all_funcs_index)
                resolved_name = (
                    f"{target_func['file']}/{target_func['class']}.{target_func['name']}"
                    if target_func and "class" in target_func and "file" in target_func
                    else f"{func_data['file']}/{call}"
                )
                children.append(resolved_name)

            yield func_name, children

    @staticmethod
    async def extract_endpoints(prefix: str) -> List[Dict[str, Any]]:
        """Собирает все эндпоинты проекта за один проход"""
        endpoints = []
        keys = await object_manager.repo.get_filenames(prefix)
        py_files = [k for k in keys if k.endswith(".py")]

        for file_key in py_files:
            try:
                funcs = await Parser.parse_python_file_s3(file_key)
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
        files = await Parser.find_dependencies_files_s3(prefix)

        for file_key in files:
            try:
                if file_key.endswith(".txt"):
                    deps = await Parser.parse_requirements_s3(file_key)
                    result[os.path.basename(file_key)] = deps
                elif file_key.endswith(".toml"):
                    deps = await Parser.parse_pyproject_s3(file_key)
                    result[os.path.basename(file_key)] = deps
            except Exception as e:
                print(f"Ошибка при чтении зависимостей из {file_key}: {e}")

        return result

# async def main():
#     from utils.logger import create_logger
#     log = create_logger("EnhancedFunctionParser")
#     log.info(f"Начало")
#     project_path_s3 = r"12/core.zip/3bcbeadd-58a2-412b-b15f-279d319f8d54/None/unpacked/"
#
#     endpoints_raw = await EnhancedFunctionParser.extract_endpoints(project_path_s3)
#     log.info(f"Извлечены эндпоинты")
#     log.info(f"Эндпоинты сырые: {endpoints_raw}")
#     endpoints = {item["function"]: item["method"] + " " + item["path"] for item in endpoints_raw}
#     log.info(f"Эндпоинты: {endpoints}")
# # Пример использования
# if __name__ == "__main__":
#     asyncio.run(main())

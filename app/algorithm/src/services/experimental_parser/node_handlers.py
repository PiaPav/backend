from services.experimental_parser.node_extractors import NodeExtractors
from services.experimental_parser.utils import normalize_path


class NodeHandlers:
    """
    Миксин с обработчиками узлов tree-sitter.
    Требует внедрения зависимостей через __init__ или атрибуты.

    Ожидаемые атрибуты/методы у родителя:
    - self.code_bytes, self.import_resolver, self.scope_manager,
      self.dependency_tracker, self.definitions, self.instance_of, self.aliases
    - self._walk(), NodeExtractors.extract_text(), NodeExtractors.extract_call_name()
    """

    def _handle_import_statement(self, node):
        """Обрабатывает операторы импорта и регистрирует алиасы в текущей области."""
        text = NodeExtractors.extract_text(self.code_bytes, node).replace("import ", "")
        for part in text.split(","):
            part = part.strip()
            if " as " in part:
                name, alias = part.split(" as ")
                name, alias = name.strip(), alias.strip()
                resolved = self.import_resolver.resolve_import(name) or name
                self.aliases[alias] = resolved
            else:
                name = part
                resolved = self.import_resolver.resolve_import(name) or name
                self.aliases[name] = resolved

    def _handle_import_from_statement(self, node):
        """Обрабатывает операторы from ... import и разрешает относительные импорты."""
        text = NodeExtractors.extract_text(self.code_bytes, node)
        if "import" not in text:
            return
        from_part, import_part = text.split("import", 1)
        from_part = from_part.replace("from", "").strip()
        imports = [x.strip() for x in import_part.split(",")]
        if from_part.startswith("."):
            base_path = self.import_resolver.resolve_relative_import(from_part, self.scope_manager.current_file)
        else:
            resolved_file = self.import_resolver.resolve_import(from_part)
            base_path = resolved_file if resolved_file else from_part.replace(".", "/")
        for imp in imports:
            imp_name = alias_name = imp
            if " as " in imp:
                imp_name, alias_name = [x.strip() for x in imp.split(" as ")]
            if base_path.endswith(".py"):
                target = f"{base_path}.{imp_name}"
            else:
                potential_file = f"{base_path}/{imp_name}.py"
                if potential_file in self.import_resolver.project_files:
                    target = potential_file
                else:
                    target = f"{base_path}.{imp_name}"
            self.aliases[alias_name] = target

    def _handle_assignment(self, node):
        """Обрабатывает присваивания, отслеживая атрибуты и экземпляры классов."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left and left.type == "identifier":
            var = NodeExtractors.extract_text(self.code_bytes, left)
            current_scope = self.scope_manager.get_current_scope()
            full_var_name = f"{current_scope}.{var}"
            is_module_level = self.scope_manager.is_module_level()
            is_class_level = self.scope_manager.is_class_level()
            if is_module_level:
                self.definitions['attributes'].add(full_var_name)
                if right and right.type == "call":
                    func_node = right.child_by_field_name("function")
                    if func_node:
                        class_name = NodeExtractors.extract_call_name(self.code_bytes, func_node)
                        if class_name:
                            resolved_class = self.import_resolver.resolve_full_name(class_name, self.aliases)
                            self.instance_of[full_var_name] = resolved_class
                            if self.dependency_tracker._is_user_call(resolved_class):
                                self.dependency_tracker.add_dependency(full_var_name, resolved_class)
                self.aliases[var] = full_var_name
            elif is_class_level:
                self.definitions['attributes'].add(full_var_name)
        for child in node.children:
            self._walk(child)

    def _handle_function_definition(self, node):
        """Обрабатывает определения функций, управляя областью видимости и регистрируя методы."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = NodeExtractors.extract_text(self.code_bytes, name_node)
        parent = node.parent
        if parent and parent.type == "block":
            grandparent = parent.parent
            if grandparent and grandparent.type == "class_definition":
                if len(self.scope_manager.scope_stack) >= 1:
                    full_name = f"{self.scope_manager.get_current_scope()}.{name}"
                    if full_name in self.definitions['attributes']:
                        for child in node.children:
                            self._walk(child)
                        return
        scope = self.scope_manager.get_current_scope()
        self.result.setdefault(scope, [])
        self.scope_manager.push_scope('function', name)
        full_method_name = self.scope_manager.get_current_scope()
        self.definitions['methods'].add(full_method_name)
        self.result[full_method_name] = []
        for child in node.children:
            self._walk(child)
        self.scope_manager.pop_scope()

    def _handle_class_definition(self, node):
        """Обрабатывает определения классов, регистрируя их и управляя вложенной областью видимости."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = NodeExtractors.extract_text(self.code_bytes, name_node)
        full_name = f"{normalize_path(self.scope_manager.current_file)}.{name}"
        self.aliases[name] = full_name
        self.result.setdefault(full_name, [])
        self.definitions['classes'].add(full_name)
        self.scope_manager.push_scope('class', name)
        for child in node.children:
            self._walk(child)
        self.scope_manager.pop_scope()

    def _handle_call(self, node):
        """Обрабатывает вызовы функций и регистрирует зависимости."""
        func_node = node.child_by_field_name("function")
        name = NodeExtractors.extract_call_name(self.code_bytes, func_node)
        if name:
            self.dependency_tracker.add_call(name, self.scope_manager.get_current_scope(), self.aliases)
        for child in node.children:
            self._walk(child)

    def _handle_await_expression(self, node):
        """Обрабатывает выражения await, рекурсивно обходя аргумент."""
        arg_node = node.child_by_field_name("argument")
        if arg_node:
            self._walk(arg_node)

    def _handle_attribute(self, node):
        """Обрабатывает обращения к атрибутам и регистрирует зависимости для атрибутов экземпляров."""
        name = NodeExtractors.extract_call_name(self.code_bytes, node)
        if name:
            parts = name.split(".")
            if len(parts) >= 2:
                first_part = parts[0]
                if first_part in self.aliases:
                    current_scope = self.scope_manager.get_current_scope()
                    full_var_name = f"{current_scope}.{first_part}"
                    if full_var_name in self.definitions['attributes']:
                        stored_name = f"{full_var_name}.{'.'.join(parts[1:])}"
                        self.dependency_tracker.add_dependency(current_scope, stored_name)
                        for child in node.children:
                            self._walk(child)
                        return
            self.dependency_tracker.add_call(name, self.scope_manager.get_current_scope(), self.aliases)
        for child in node.children:
            self._walk(child)

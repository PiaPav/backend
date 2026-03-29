from typing import Optional


class NodeExtractors:
    """
    Миксин для извлечения имён и текста из узлов tree-sitter.
    Не содержит состояния, только чистые методы.
    """

    @staticmethod
    def extract_text(code_bytes: bytes, node) -> str:
        """Извлекает текстовое содержимое узла из байтов исходного кода."""
        return code_bytes[node.start_byte:node.end_byte].decode()

    @staticmethod
    def extract_call_name(code_bytes: bytes, node) -> Optional[str]:
        """Извлекает имя вызова функции из узла tree-sitter, поддерживая идентификаторы, атрибуты и вложенные вызовы."""
        if not node:
            return None
        if node.type == "identifier":
            return NodeExtractors.extract_text(code_bytes, node)
        if node.type == "attribute":
            parts = []
            current = node
            while current and current.type == "attribute":
                attr = current.child_by_field_name("attribute")
                if attr:
                    parts.append(NodeExtractors.extract_text(code_bytes, attr))
                current = current.child_by_field_name("object")
            if current and current.type == "call":
                inner = NodeExtractors.extract_call_name(code_bytes, current.child_by_field_name("function"))
                if inner:
                    parts.append(inner)
            elif current and current.type == "identifier":
                parts.append(NodeExtractors.extract_text(code_bytes, current))
            return ".".join(reversed(parts))
        if node.type == "call":
            return NodeExtractors.extract_call_name(code_bytes, node.child_by_field_name("function"))
        return None

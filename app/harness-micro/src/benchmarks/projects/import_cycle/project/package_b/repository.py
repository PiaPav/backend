from package_a import service


def fetch_item(item_id: str) -> str:
    return f"item:{item_id}"


def refresh_item(item_id: str) -> str:
    return service.load_item(item_id)

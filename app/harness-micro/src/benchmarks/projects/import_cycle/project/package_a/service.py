from package_b import repository


def load_item(item_id: str) -> str:
    return repository.fetch_item(item_id)

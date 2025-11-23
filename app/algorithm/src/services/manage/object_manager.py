from infrastructure.object_storage.interface import AbstractStorage
from infrastructure.object_storage.object_storage_manager import ObjectStorageManager
from utils.logger import create_logger

log = create_logger("ObjectManagerService")

class ObjectManager:
    def __init__(self, repo: AbstractStorage):
        self.repo = repo

s3_repo = ObjectStorageManager()
object_manager = ObjectManager(s3_repo)

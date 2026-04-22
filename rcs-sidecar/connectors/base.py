from abc import ABC, abstractmethod
from pydantic import BaseModel

class FileEntry(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    modified_at: str
    path: str

class Connector(ABC):
    @abstractmethod
    async def list_files(self, path: str = "/", query: str = "") -> list[FileEntry]:
        pass

    @abstractmethod
    async def fetch_file(self, file_id: str) -> tuple[bytes, str]:
        pass

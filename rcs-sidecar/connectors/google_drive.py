from .base import Connector, FileEntry
import os
import json
import redis.asyncio as redis
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

REDIS_URL = os.getenv("REDIS_URL")

class GoogleDriveConnector(Connector):
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._redis = redis.from_url(REDIS_URL) if REDIS_URL else None

    async def _get_credentials(self):
        if not self._redis: return None
        creds_json = await self._redis.get(f"gdrive_creds:{self.project_id}")
        if not creds_json: return None
        return Credentials.from_authorized_user_info(json.loads(creds_json))

    async def list_files(self, path: str = "root", query: str = "") -> list[FileEntry]:
        creds = await self._get_credentials()
        if not creds: raise Exception("Not authenticated with Google Drive")
        
        service = build('drive', 'v3', credentials=creds)
        q = f"'{path}' in parents and trashed=false"
        if query: q += f" and name contains '{query}'"
        
        results = service.files().list(q=q, fields="files(id, name, mimeType, size, modifiedTime)").execute()
        files = results.get('files', [])
        
        return [FileEntry(
            file_id=f['id'], filename=f['name'], mime_type=f['mimeType'],
            size_bytes=int(f.get('size', 0)), modified_at=f.get('modifiedTime', ''), path=path
        ) for f in files]

    async def fetch_file(self, file_id: str) -> tuple[bytes, str]:
        creds = await self._get_credentials()
        if not creds: raise Exception("Not authenticated with Google Drive")
        
        service = build('drive', 'v3', credentials=creds)
        file_meta = service.files().get(fileId=file_id).execute()
        request = service.files().get_media(fileId=file_id)
        
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            
        return fh.getvalue(), file_meta['name']

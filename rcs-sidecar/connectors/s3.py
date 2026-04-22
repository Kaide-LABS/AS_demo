from .base import Connector, FileEntry
import os
import asyncio

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore

class S3Connector(Connector):
    def __init__(self, bucket: str, aws_access_key_id: str = None, aws_secret_access_key: str = None):
        self.bucket = bucket
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        )

    async def list_files(self, path: str = "", query: str = "") -> list[FileEntry]:
        def _list():
            resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=path)
            return resp.get('Contents', [])
            
        contents = await asyncio.to_thread(_list)
        
        return [FileEntry(
            file_id=c['Key'], filename=c['Key'].split('/')[-1], mime_type='application/octet-stream',
            size_bytes=c['Size'], modified_at=str(c['LastModified']), path=c['Key']
        ) for c in contents if query in c['Key']]

    async def fetch_file(self, file_id: str) -> tuple[bytes, str]:
        def _fetch():
            resp = self.s3.get_object(Bucket=self.bucket, Key=file_id)
            return resp['Body'].read()
            
        data = await asyncio.to_thread(_fetch)
        return data, file_id.split('/')[-1]

async def parse(file_bytes: bytes, filename: str):
    return file_bytes.decode('utf-8', errors='replace'), [], {"encoding": "utf-8"}

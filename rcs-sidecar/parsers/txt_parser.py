async def parse(file_bytes: bytes, filename: str):
    try:
        raw_text = file_bytes.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        raw_text = file_bytes.decode("latin-1")
        encoding = "latin-1"
    return raw_text, [], {"encoding": encoding, "char_count": len(raw_text)}

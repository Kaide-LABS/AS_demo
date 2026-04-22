import io
import pandas as pd


async def parse(file_bytes: bytes, filename: str):
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), sep=None, engine="python")
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes))

    truncated = len(df) > 500
    raw_text = df.head(500).to_string(index=False)
    tables = df.head(500).to_dict(orient="records")
    metadata = {
        "row_count": len(df),
        "column_names": list(df.columns),
        "truncated": truncated,
    }
    return raw_text, tables, metadata

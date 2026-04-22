import io
import pandas as pd


async def parse(file_bytes: bytes, filename: str):
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, engine="openpyxl")
    parts = []
    all_records = []
    total_rows = 0
    for name, df in sheets.items():
        total_rows += len(df)
        parts.append(f"--- Sheet: {name} ---\n{df.head(500).to_string(index=False)}")
        all_records.extend(df.head(500).to_dict(orient="records"))

    raw_text = "\n\n".join(parts)
    metadata = {
        "sheet_names": list(sheets.keys()),
        "total_rows": total_rows,
        "truncated": total_rows > 500,
    }
    return raw_text, all_records[:500], metadata

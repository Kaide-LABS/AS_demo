import tempfile
import os
import pyreadstat


async def parse(file_bytes: bytes, filename: str):
    tmp = tempfile.NamedTemporaryFile(suffix=".sav", delete=False)
    try:
        tmp.write(file_bytes)
        tmp.close()
        df, meta = pyreadstat.read_sav(tmp.name)
    finally:
        os.unlink(tmp.name)

    truncated = len(df) > 500
    raw_text = df.head(500).to_csv(index=False)
    tables = df.head(500).to_dict(orient="records")
    metadata = {
        "row_count": len(df),
        "column_names": list(df.columns),
        "variable_labels": meta.column_names_to_labels,
        "value_labels": {k: dict(v) for k, v in meta.variable_value_labels.items()},
        "truncated": truncated,
    }
    return raw_text, tables, metadata

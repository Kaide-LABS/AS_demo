import uuid
import magic
from schemas import SourceArtifact
from parsers import pdf_parser, image_parser, spss_parser, csv_parser, xlsx_parser, qsf_parser, docx_parser, txt_parser
from fastapi import UploadFile

async def detect_and_parse(upload: UploadFile) -> SourceArtifact:
    file_bytes = await upload.read()
    filename = upload.filename or "unknown"
    
    mime_type = magic.from_buffer(file_bytes[:2048], mime=True)
    
    if mime_type == "application/pdf":
        raw_text, tables, metadata = await pdf_parser.parse(file_bytes, filename)
    elif mime_type.startswith("image/"):
        raw_text, tables, metadata = await image_parser.parse(file_bytes, filename)
    elif mime_type == "application/x-spss-sav":
        raw_text, tables, metadata = await spss_parser.parse(file_bytes, filename)
    elif mime_type == "text/csv":
        raw_text, tables, metadata = await csv_parser.parse(file_bytes, filename)
    elif mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        raw_text, tables, metadata = await xlsx_parser.parse(file_bytes, filename)
    elif mime_type == "application/json" and filename.endswith(".qsf"):
        raw_text, tables, metadata = await qsf_parser.parse(file_bytes, filename)
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        raw_text, tables, metadata = await docx_parser.parse(file_bytes, filename)
    else:
        raw_text, tables, metadata = await txt_parser.parse(file_bytes, filename)
        
    return SourceArtifact(
        artifact_id=str(uuid.uuid4()),
        filename=filename,
        raw_text=raw_text,
        tables=tables,
        metadata=metadata,
        size_bytes=len(file_bytes)
    )

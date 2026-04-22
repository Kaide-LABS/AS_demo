import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES_DIR, name), "rb") as f:
        return f.read()


@pytest.mark.asyncio
async def test_csv_parser_reads_real_csv():
    from parsers.csv_parser import parse
    raw, tables, meta = await parse(_read_fixture("kantar_brand_tracker.csv"), "kantar.csv")
    assert meta["row_count"] == 4
    assert "Institutional Investors" in raw
    assert len(meta["column_names"]) == 6


@pytest.mark.asyncio
async def test_txt_parser_handles_utf8():
    from parsers.txt_parser import parse
    raw, tables, meta = await parse("Hello résumé café".encode("utf-8"), "test.txt")
    assert "résumé" in raw
    assert meta["encoding"] == "utf-8"


@pytest.mark.asyncio
async def test_txt_parser_falls_back_to_latin1():
    from parsers.txt_parser import parse
    raw, tables, meta = await parse("Hello résumé".encode("latin-1"), "test.txt")
    assert "résumé" in raw
    assert meta["encoding"] == "latin-1"


@pytest.mark.asyncio
async def test_csv_parser_truncates_large_files():
    from parsers.csv_parser import parse
    lines = ["col_a,col_b"] + [f"val_{i},data_{i}" for i in range(600)]
    raw, tables, meta = await parse("\\n".join(lines).encode(), "big.csv")
    assert meta["row_count"] == 600
    assert meta["truncated"] is True
    assert len(tables) == 500

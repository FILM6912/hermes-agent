"""Vector replace/delete must scope by document set when document_name is known."""

from app.document_api.services.document_pipeline import _vector_rows_for_source_sql


def test_vector_rows_for_source_sql_without_document_name():
    sql, params = _vector_rows_for_source_sql(None)
    assert "document_name" not in sql
    assert params == []


def test_vector_rows_for_source_sql_scopes_to_document_set():
    sql, params = _vector_rows_for_source_sql("012.MACHINING BASIC DESIGN")
    assert "metadata->>'source_filename'" in sql
    assert "document_name" in sql
    assert params == ["012.MACHINING BASIC DESIGN", "012.MACHINING BASIC DESIGN"]

from fastapi import APIRouter, HTTPException, Query, Body, UploadFile, File
from pydantic import BaseModel
from typing import Dict, Any
import psycopg
from psycopg.rows import dict_row
import os

# --------------------------------------------------
# DATABASE CONFIG
# --------------------------------------------------
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
if not POSTGRES_CONNECTION_STRING:
    raise ValueError("POSTGRES_CONNECTION_STRING is not set")

# Initialize FastAPI router
router = APIRouter(prefix="/app_db", tags=["app_db"])

# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------
def get_conn():
    """Return a new DB connection using psycopg."""
    return psycopg.connect(POSTGRES_CONNECTION_STRING, row_factory=dict_row)

# --------------------------------------------------
# MULTILINE RAW SQL ENDPOINT
# --------------------------------------------------
class SQLQuery(BaseModel):
    sql_query: str  # Can be multiline SQL

@router.post("/api/database/query")
def run_any_query(query: SQLQuery = Body(..., media_type="application/json")):
    """
    Execute any SQL query (single-line per statement, multiline supported).
    ⚠️ WARNING: Executes raw SQL. Only for trusted/demo use.
    ```json
    { "sql_query": "
        CREATE TABLE product_test (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, price NUMERIC(10,2) NOT NULL, stock INT DEFAULT 0);
        INSERT INTO product_test (name, price, stock) VALUES ('Mouse', 49.99, 100), ('Keyboard', 89.99, 50), ('Monitor', 199.99, 20);
        SELECT * FROM product_test;
        UPDATE product_test SET price = 79.99, stock = 60 WHERE name = 'Keyboard';
        DELETE FROM product_test WHERE name = 'Mouse';
        DROP TABLE product_test; 
        "
    }
    """

    sql = query.sql_query
    if not sql.strip():
        raise HTTPException(400, "SQL query cannot be empty")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql)
            if cur.description:
                rows = cur.fetchall()
                return {"row_count": len(rows), "data": rows}
            conn.commit()
            return {"status": "success", "rows_affected": cur.rowcount}
        except Exception as e:
            conn.rollback()
            raise HTTPException(400, f"SQL execution error: {str(e)}")

# --------------------------------------------------
# UPLOAD SQL FILE
# --------------------------------------------------
@router.post("/api/database/upload_sql")
def upload_sql(file: UploadFile = File(...)):
    """
    Upload a .sql file and execute it.
    Example: upload products.sql containing CREATE TABLE + INSERT statements
    """
    content = file.file.read().decode("utf-8")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(content)
            conn.commit()
            return {"status": "success"}
        except Exception as e:
            conn.rollback()
            raise HTTPException(400, f"SQL execution error: {str(e)}")

# --------------------------------------------------
# GET TABLE SCHEMA
# --------------------------------------------------
@router.get("/api/{table}/schema")
def get_table_schema(table: str):
    """
    Fetch table columns and data types.
    Example: GET /app_db/api/products/schema
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        schema = cur.fetchall()
    return {"table": table, "columns": schema}
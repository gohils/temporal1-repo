import psycopg
import sys

# =========================
# CONFIG
# =========================
DB_HOST = "zdb1.postgres.database.azure.com"
DB_PORT = 5432
DB_USER = "sqladmin"
DB_PASSWORD = "Zsupabase~1"

DB_NAME = "postgres"


def execute_sql(conn, sql: str):
    """Execute a single SQL statement safely."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            print(f"Executed: {sql}")
    except Exception as e:
        print(f"Error executing SQL: {sql}")
        print(str(e))


def main():
    try:
        print("Connecting to PostgreSQL (psycopg v3)...")

        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME,

            # 🔐 REQUIRED for Azure PostgreSQL
            sslmode="require"
        )

        # psycopg3 uses autocommit differently
        conn.autocommit = True

        print("Connected successfully")

        # =========================
        # Create databases
        # =========================
        execute_sql(conn, "CREATE DATABASE temporal;")
        execute_sql(conn, "CREATE DATABASE temporal_visibility;")

        print("Databases created successfully")

    except Exception as e:
        print("Connection failed or error occurred:")
        print(str(e))
        sys.exit(1)

    finally:
        try:
            conn.close()
        except:
            pass


if __name__ == "__main__":
    main()
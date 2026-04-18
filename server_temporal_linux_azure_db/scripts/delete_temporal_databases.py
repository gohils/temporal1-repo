import psycopg
import sys

DB_HOST = "zdb1.postgres.database.azure.com"
DB_PORT = 5432
DB_USER = "sqladmin"
DB_PASSWORD = "Zsupabase~1"

DB_NAME = "postgres"


def execute_sql(conn, sql: str):
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            print(f"Executed: {sql}")
    except Exception as e:
        print(f"Error executing SQL: {sql}")
        print(str(e))


def terminate_db_connections(conn, db_name: str):
    print(f"Terminating connections to {db_name}...")

    sql = f"""
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = '{db_name}'
      AND pid <> pg_backend_pid();
    """

    execute_sql(conn, sql)


def drop_db(conn, db_name: str):
    execute_sql(conn, f'DROP DATABASE IF EXISTS "{db_name}";')


def main():
    try:
        print("Connecting...")

        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME,
            sslmode="require"
        )

        conn.autocommit = True
        print("Connected successfully")

        # Step 1: kill sessions
        terminate_db_connections(conn, "temporal")
        terminate_db_connections(conn, "temporal_visibility")

        # Step 2: drop DBs
        drop_db(conn, "temporal")
        drop_db(conn, "temporal_visibility")

        print("Databases dropped successfully")

    except Exception as e:
        print("Error occurred:")
        print(str(e))
        sys.exit(1)

    finally:
        try:
            conn.close()
        except:
            pass


if __name__ == "__main__":
    main()
import psycopg
import sys

# =========================
# CONFIG
# =========================
DB_HOST = "zdb1.postgres.database.azure.com"
DB_PORT = 5432
DB_USER = "sqladmin"
DB_PASSWORD = "Zsupabase~1"

DBS_TO_TEST = ["postgres", "temporal", "temporal_visibility"]

EXTENSIONS = ["btree_gin", "pg_trgm", "btree_gist"]


def run_sql(conn, sql):
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            try:
                return cur.fetchall()
            except:
                return None
    except Exception as e:
        return str(e)


def test_extensions(conn, dbname):
    print("\n" + "=" * 60)
    print(f"Testing DB: {dbname}")
    print("=" * 60)

    # 1. Check available extensions
    print("\n📌 Available extensions (Azure allow-list view):")
    res = run_sql(conn, "SELECT name FROM pg_available_extensions;")
    if isinstance(res, list):
        available = {r[0] for r in res}
        for ext in EXTENSIONS:
            print(f" - {ext}: {'AVAILABLE' if ext in available else 'NOT AVAILABLE'}")
    else:
        print("Error fetching extensions:", res)

    # 2. Try CREATE EXTENSION (REAL test)
    for ext in EXTENSIONS:
        print(f"\n⚙️ Testing CREATE EXTENSION {ext} ...")

        result = run_sql(conn, f"CREATE EXTENSION IF NOT EXISTS {ext};")

        if result is None:
            print(f"✅ {ext}: CREATE SUCCESS")
        else:
            print(f"❌ {ext}: FAILED")
            print(f"   Reason: {result}")


def main():
    try:
        print("Connecting to Azure PostgreSQL...")

        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname="postgres",
            sslmode="require"
        )

        conn.autocommit = True

        print("Connected successfully")

        # 3. Loop through databases
        for db in DBS_TO_TEST:
            try:
                # reconnect per DB (important in Postgres)
                conn.close()

                conn = psycopg.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    dbname=db,
                    sslmode="require"
                )
                conn.autocommit = True

                test_extensions(conn, db)

            except Exception as e:
                print(f"\n❌ Cannot connect to DB {db}")
                print(str(e))

    except Exception as e:
        print("Connection failed:")
        print(str(e))
        sys.exit(1)

    finally:
        try:
            conn.close()
        except:
            pass


if __name__ == "__main__":
    main()
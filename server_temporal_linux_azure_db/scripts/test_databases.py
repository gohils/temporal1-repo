import sys
import psycopg
import time
from datetime import datetime
from psycopg.rows import dict_row

# ======================================================
# CONFIGURATION
# ======================================================
DB_HOST = "zdb1.postgres.database.azure.com"
DB_PORT = 5432
DB_USER = "sqladmin"
DB_PASSWORD = "Zsupabase~1"
DB_NAME = "postgres"

SSL_MODE = "require"

# ======================================================
# CONNECTION
# ======================================================
def get_connection(db_name: str = DB_NAME):
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=db_name,
        sslmode=SSL_MODE,
        row_factory=dict_row,
    )


# ======================================================
# HELPER
# ======================================================
def print_section(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def run_query(conn, sql: str, description: str):
    print_section(description)
    try:
        with conn.cursor() as cur:
            start = time.time()
            cur.execute(sql)

            rows = cur.fetchall() if cur.description else []
            elapsed = round((time.time() - start) * 1000, 2)

            print(f"Query completed in {elapsed} ms")

            if not rows:
                print("No rows returned")
                return

            for row in rows:
                print(row)

    except Exception as e:
        print(f"ERROR: {e}")


# ======================================================
# DIAGNOSTIC QUERIES
# ======================================================

def check_connection_health(conn):
    run_query(
        conn,
        """
        SELECT
            now() AS server_time,
            version() AS postgres_version,
            current_database() AS database_name,
            inet_server_addr() AS server_ip,
            inet_client_addr() AS client_ip;
        """,
        "Connection / Server Health",
    )


def check_active_connections(conn):
    run_query(
        conn,
        """
        SELECT
            datname,
            usename,
            state,
            wait_event_type,
            wait_event,
            count(*) AS connection_count
        FROM pg_stat_activity
        GROUP BY datname, usename, state, wait_event_type, wait_event
        ORDER BY connection_count DESC;
        """,
        "Active Connections Summary",
    )


def check_long_running_queries(conn):
    run_query(
        conn,
        """
        SELECT
            pid,
            now() - query_start AS duration,
            state,
            wait_event_type,
            wait_event,
            left(query, 200) AS query
        FROM pg_stat_activity
        WHERE query NOT ILIKE '%pg_stat_activity%'
          AND state <> 'idle'
        ORDER BY duration DESC
        LIMIT 20;
        """,
        "Long Running Queries",
    )


def check_temporal_database_stats(conn):
    run_query(
        conn,
        """
        SELECT
            datname,
            numbackends,
            xact_commit,
            xact_rollback,
            blks_read,
            blks_hit,
            tup_returned,
            tup_fetched,
            tup_inserted,
            tup_updated,
            tup_deleted
        FROM pg_stat_database
        WHERE datname IN ('temporal', 'temporal_visibility');
        """,
        "Temporal Database Statistics",
    )


def check_locks(conn):
    run_query(
        conn,
        """
        SELECT
            locktype,
            mode,
            granted,
            count(*) AS total
        FROM pg_locks
        GROUP BY locktype, mode, granted
        ORDER BY total DESC;
        """,
        "Lock Contention Summary",
    )


def check_blocked_queries(conn):
    run_query(
        conn,
        """
        SELECT
            blocked.pid AS blocked_pid,
            blocked.query AS blocked_query,
            blocking.pid AS blocking_pid,
            blocking.query AS blocking_query
        FROM pg_catalog.pg_locks blocked_locks
        JOIN pg_catalog.pg_stat_activity blocked
            ON blocked.pid = blocked_locks.pid
        JOIN pg_catalog.pg_locks blocking_locks
            ON blocking_locks.locktype = blocked_locks.locktype
            AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
            AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
            AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
            AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
            AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
            AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
            AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
            AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
            AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
            AND blocking_locks.pid != blocked_locks.pid
        JOIN pg_catalog.pg_stat_activity blocking
            ON blocking.pid = blocking_locks.pid
        WHERE NOT blocked_locks.granted;
        """,
        "Blocked Queries",
    )


def check_table_sizes(conn):
    run_query(
        conn,
        """
        SELECT
            schemaname,
            relname AS table_name,
            pg_size_pretty(pg_total_relation_size(relid)) AS total_size
        FROM pg_catalog.pg_statio_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 20;
        """,
        "Largest Tables",
    )


def benchmark_simple_query(conn):
    print_section("Simple Query Benchmark")

    iterations = 20
    durations = []

    with conn.cursor() as cur:
        for i in range(iterations):
            start = time.time()
            cur.execute("SELECT 1;")
            cur.fetchone()
            durations.append((time.time() - start) * 1000)

    avg_ms = round(sum(durations) / len(durations), 2)
    max_ms = round(max(durations), 2)
    min_ms = round(min(durations), 2)

    print(f"Iterations: {iterations}")
    print(f"Average latency: {avg_ms} ms")
    print(f"Min latency: {min_ms} ms")
    print(f"Max latency: {max_ms} ms")

    if avg_ms > 100:
        print("⚠️ WARNING: Query latency is high for Temporal")
    elif avg_ms > 30:
        print("⚠️ Latency is acceptable but may slow Temporal UI/workers")
    else:
        print("✅ Query latency looks healthy")


# ======================================================
# MAIN
# ======================================================
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Azure PostgreSQL diagnostics...")

    try:
        conn = get_connection()
        conn.autocommit = True

        print("Connected successfully")

        check_connection_health(conn)
        check_active_connections(conn)
        check_long_running_queries(conn)
        check_temporal_database_stats(conn)
        check_locks(conn)
        check_blocked_queries(conn)
        check_table_sizes(conn)
        benchmark_simple_query(conn)

        print("\nDiagnostics complete")

    except Exception as e:
        print(f"FAILED: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

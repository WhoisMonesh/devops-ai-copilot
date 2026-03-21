# agent/tools/database_tool.py
# Database tools for DevOps AI Copilot - PostgreSQL, MySQL, Redis, MongoDB

import logging
import os

import redis
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _get_postgres_conn():
    """Get PostgreSQL connection."""
    import psycopg2
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    dbname = os.getenv("PGDATABASE", "postgres")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    return psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)


def _get_mysql_conn():
    """Get MySQL connection."""
    import pymysql
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    dbname = os.getenv("MYSQL_DATABASE", "mysql")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    return pymysql.connect(host=host, port=port, database=dbname, user=user, password=password)


def _get_redis_client():
    """Get Redis client."""
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD", None)
    db = int(os.getenv("REDIS_DB", "0"))
    return redis.Redis(host=host, port=port, password=password, db=db, decode_responses=True)


@tool
def postgres_list_databases() -> str:
    """List all PostgreSQL databases."""
    try:
        conn = _get_postgres_conn()
        cur = conn.cursor()
        cur.execute("SELECT datname, datistemplate, datallowconn FROM pg_database WHERE datistemplate = false")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        lines = [f"PostgreSQL Databases ({len(rows)}):"]
        for r in rows:
            lines.append(f"  {r[0]} | AllowConn: {r[2]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("postgres_list_databases failed")
        return f"Error listing PostgreSQL databases: {e}"


@tool
def postgres_get_activity() -> str:
    """Get current PostgreSQL activity - active queries and connections."""
    try:
        conn = _get_postgres_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT pid, usename, application_name, state, query, query_start
            FROM pg_stat_activity
            WHERE datname = current_database()
            AND pid <> pg_backend_pid()
            ORDER BY query_start
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return "No active connections or queries."

        lines = [f"PostgreSQL Activity ({len(rows)} sessions):"]
        for r in rows:
            state = r[3] or "unknown"
            query = (r[4] or "")[:80]
            lines.append(f"  [{r[0]}] {r[1]} | {state} | {query} | {r[5]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("postgres_get_activity failed")
        return f"Error getting PostgreSQL activity: {e}"


@tool
def postgres_table_sizes(limit: int = 20) -> str:
    """Get PostgreSQL table sizes.
    Args:
      limit - Number of largest tables to show (default: 20)"""
    try:
        conn = _get_postgres_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT schemaname, tablename,
                   pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                   pg_total_relation_size(schemaname||'.'||tablename) AS bytes
            FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY bytes DESC
            LIMIT {limit}
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        lines = [f"PostgreSQL Table Sizes (top {len(rows)}):"]
        for r in rows:
            lines.append(f"  {r[0]}.{r[1]} | {r[2]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("postgres_table_sizes failed")
        return f"Error getting table sizes: {e}"


@tool
def postgres_replication_status() -> str:
    """Get PostgreSQL replication status (replicas and slots)."""
    try:
        conn = _get_postgres_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
                   sync_state
            FROM pg_stat_replication
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return "No active PostgreSQL replications."

        lines = [f"PostgreSQL Replication ({len(rows)} replicas):"]
        for r in rows:
            lines.append(f"  {r[0]} | {r[5]} | Sync: {r[6]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("postgres_replication_status failed")
        return f"Error getting replication status: {e}"


@tool
def mysql_status() -> str:
    """Get MySQL server status overview."""
    try:
        conn = _get_mysql_conn()
        cur = conn.cursor()
        cur.execute("SHOW STATUS LIKE 'Uptime'")
        uptime = cur.fetchone()
        cur.execute("SHOW STATUS LIKE 'Threads_connected'")
        threads = cur.fetchone()
        cur.execute("SHOW STATUS LIKE 'Queries'")
        queries = cur.fetchone()
        cur.execute("SHOW DATABASES")
        dbs = cur.fetchall()
        cur.close()
        conn.close()

        lines = [
            "MySQL Server Status:",
            f"  Uptime: {uptime[1] if uptime else 'N/A'}",
            f"  Threads Connected: {threads[1] if threads else 'N/A'}",
            f"  Total Queries: {queries[1] if queries else 'N/A'}",
            f"  Databases: {len(dbs)}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.exception("mysql_status failed")
        return f"Error getting MySQL status: {e}"


@tool
def mysql_processlist() -> str:
    """Get MySQL process list with current queries."""
    try:
        conn = _get_mysql_conn()
        cur = conn.cursor()
        cur.execute("SHOW FULL PROCESSLIST")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return "No MySQL processes found."

        lines = [f"MySQL Process List ({len(rows)} processes):"]
        for r in rows:
            lines.append(f"  [{r[0]}] {r[2]}@{r[3]} | {r[4]} | {str(r[7])[:60]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("mysql_processlist failed")
        return f"Error getting MySQL process list: {e}"


@tool
def redis_info() -> str:
    """Get Redis server information and stats."""
    try:
        client = _get_redis_client()
        info = client.info()

        lines = [
            "Redis Server Info:",
            f"  Redis Version: {info.get('redis_version', 'N/A')}",
            f"  Uptime (seconds): {info.get('uptime_in_seconds', 'N/A')}",
            f"  Connected Clients: {info.get('connected_clients', 'N/A')}",
            f"  Memory Used: {info.get('used_memory_human', 'N/A')}",
            f"  Total Connections: {info.get('total_connections_received', 'N/A')}",
            f"  Total Commands: {info.get('total_commands_processed', 'N/A')}",
            f"  Keyspace (keys): {info.get('db0', {}).get('keys', 'N/A')}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.exception("redis_info failed")
        return f"Error getting Redis info: {e}"


@tool
def redis_get_keys(pattern: str = "*", count: int = 50) -> str:
    """Get Redis keys matching a pattern.
    Args:
      pattern - Key pattern (default: * for all)
      count - Maximum number of keys to return (default: 50)"""
    try:
        client = _get_redis_client()
        keys = client.keys(pattern)[:count]

        if not keys:
            return f"No Redis keys found matching '{pattern}'."

        # Get type for each key
        lines = [f"Redis Keys matching '{pattern}' ({len(keys)} of ~{client.dbsize()}):"]
        for k in keys:
            key_type = client.type(k)
            ttl = client.ttl(k)
            lines.append(f"  {k} | Type: {key_type} | TTL: {ttl}s")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("redis_get_keys failed")
        return f"Error getting Redis keys: {e}"


@tool
def redis_slowlog(limit: int = 10) -> str:
    """Get Redis slow log entries.
    Args:
      limit - Number of entries to show (default: 10)"""
    try:
        client = _get_redis_client()
        slow = client.slowlog_get(limit)

        if not slow:
            return "Redis slowlog is empty."

        lines = [f"Redis Slow Log ({len(slow)} entries):"]
        for i, entry in enumerate(slow):
            lines.append(f"  [{i+1}] Duration: {entry['duration']}ms | Command: {str(entry['command'])[:60]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("redis_slowlog failed")
        return f"Error getting Redis slowlog: {e}"


DATABASE_TOOLS = [
    postgres_list_databases,
    postgres_get_activity,
    postgres_table_sizes,
    postgres_replication_status,
    mysql_status,
    mysql_processlist,
    redis_info,
    redis_get_keys,
    redis_slowlog,
]

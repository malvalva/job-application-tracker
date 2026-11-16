"""MySQL connection pool and query helpers."""
import threading
from contextlib import contextmanager

from mysql.connector import pooling

# Change these to match your MySQL setup.
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "job_tracker"

_pool = None
_pool_lock = threading.Lock()


def get_db():
    """Borrow a connection from a small pool (created on first use)."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pooling.MySQLConnectionPool(
                pool_name="job_tracker", pool_size=5, pool_reset_session=True,
                host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                database=DB_NAME, charset="utf8mb4", connection_timeout=5,
            )
    return _pool.get_connection()


@contextmanager
def cursor():
    connection = get_db()
    try:
        with connection.cursor(dictionary=True) as query:
            yield query
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()  # returns the connection to the pool


def fetch_all(sql, values=()):
    with cursor() as query:
        query.execute(sql, values)
        return query.fetchall()


def fetch_one(sql, values=()):
    with cursor() as query:
        query.execute(sql, values)
        return query.fetchone()


def execute(sql, values=()):
    with cursor() as query:
        query.execute(sql, values)
        return query.lastrowid

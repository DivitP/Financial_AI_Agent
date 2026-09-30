"""Postgres implementation of the repository's small DB-API/sqlite dialect surface."""

import re
import sqlite3


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    columns = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(columns, values))


def sql_for_postgres(sql, parameters=False):
    # Replace bind markers only outside SQL literals; never interpolate parameter values.
    pieces = re.split(r"('(?:''|[^'])*')", sql)
    sql = "".join(
        (part.replace("%", "%%") if parameters else part)
        if i % 2
        else (part.replace("%", "%%") if parameters else part).replace("?", "%s")
        for i, part in enumerate(pieces)
    )
    sql = re.sub(r"INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
    sql = sql.replace(
        "MAX(until, excluded.until)", "GREATEST(quota_cooldowns.until, excluded.until)"
    )
    sql = sql.replace("%s IS NULL", "%s::text IS NULL")
    sql = sql.replace("WHERE 0", "WHERE FALSE")
    sql = re.sub(r"\bwindow\b", '"window"', sql)
    if "sqlite_master" in sql:
        sql = sql.replace("sqlite_master", "information_schema.tables").replace(
            "type='table' AND name=", "table_schema=current_schema() AND table_name="
        )
    return sql


class Connection:
    """Explicit transactions; one advisory write lock preserves SQLite atomic admission checks."""

    def __init__(self, url):
        import psycopg

        self.raw = psycopg.connect(url, autocommit=True, row_factory=row_factory, connect_timeout=5)
        self.raw.execute("SET statement_timeout='30s'")
        self.raw.execute("SET lock_timeout='5s'")
        self.in_transaction = False

    def execute(self, sql, parameters=()):
        import psycopg

        command = sql.strip().upper()
        if command in {"BEGIN", "BEGIN IMMEDIATE"}:
            if not self.in_transaction:
                self.raw.execute("BEGIN")
                self.in_transaction = True
                self.raw.execute("SELECT pg_advisory_xact_lock(870001)")
            return self.raw.cursor()
        if command.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")):
            if not self.in_transaction:
                self.execute("BEGIN")
        sql = sql_for_postgres(sql, bool(parameters))
        returning_id = bool(re.match(r"\s*INSERT INTO qa_history\b", sql, re.I))
        if returning_id:
            sql += " RETURNING id"
        try:
            cursor = self.raw.execute(sql, parameters or None)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError("Relational constraint violation") from None
        return Cursor(cursor, cursor.fetchone()["id"] if returning_id else None)

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        if self.in_transaction:
            self.raw.execute("COMMIT")
            self.in_transaction = False

    def rollback(self):
        if self.in_transaction:
            self.raw.execute("ROLLBACK")
            self.in_transaction = False

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.rollback() if kind else self.commit()
        finally:
            self.close()


class Cursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor, self.lastrowid = cursor, lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)


def install_functions(connection):
    # App-specific date functions keep persisted ISO timestamps and ordering identical.
    connection.execute("BEGIN")
    connection.raw.execute("""
        CREATE OR REPLACE FUNCTION julianday(value text, modifier text DEFAULT NULL)
        RETURNS double precision LANGUAGE SQL STABLE AS $$
          SELECT EXTRACT(EPOCH FROM
            (CASE WHEN value='now' THEN CURRENT_TIMESTAMP ELSE value::timestamptz END)
            + COALESCE(modifier::interval, interval '0'))::double precision / 86400 + 2440587.5
        $$""")
    connection.raw.execute("""
        CREATE OR REPLACE FUNCTION strftime(format text, value text)
        RETURNS text LANGUAGE SQL STABLE AS $$
          SELECT to_char(value::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
        $$""")

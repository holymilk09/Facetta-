"""DATABASE_URL normalization and engine configuration.

The point of these is that a connection string copied verbatim from the Supabase
dashboard reaches a working engine — bare scheme routed to psycopg v3, the
transaction pooler's prepared-statement incompatibility handled, and idle-drop
resilience turned on for hosted Postgres.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

import facetta.db as db

from facetta.db import engine_config, normalize_database_url


class TestNormalizeDatabaseUrl:
    def test_bare_postgresql_routes_to_psycopg_v3(self):
        url = "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres"
        assert normalize_database_url(url) == (
            "postgresql+psycopg://postgres:pw@db.abcd.supabase.co:5432/postgres"
        )

    def test_heroku_style_postgres_scheme_is_upgraded(self):
        # some dashboards still emit the legacy `postgres://` scheme
        url = "postgres://postgres:pw@db.abcd.supabase.co:5432/postgres"
        assert normalize_database_url(url) == (
            "postgresql+psycopg://postgres:pw@db.abcd.supabase.co:5432/postgres"
        )

    def test_explicit_driver_is_left_alone(self):
        for url in (
            "postgresql+psycopg://u:p@h:5432/db",
            "postgresql+asyncpg://u:p@h:5432/db",
            "postgresql+psycopg2://u:p@h:5432/db",
        ):
            assert normalize_database_url(url) == url

    def test_sqlite_is_untouched(self):
        assert normalize_database_url("sqlite:///./facetta.db") == "sqlite:///./facetta.db"


class TestEngineConfig:
    def test_sqlite_gets_thread_guard(self):
        url, kwargs = engine_config("sqlite:///./facetta.db")
        assert url == "sqlite:///./facetta.db"
        assert kwargs == {"connect_args": {"check_same_thread": False}}

    def test_direct_postgres_gets_pre_ping_no_prepare_override(self):
        url, kwargs = engine_config(
            "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres"
        )
        assert url.startswith("postgresql+psycopg://")
        assert kwargs["pool_pre_ping"] is True
        assert "connect_args" not in kwargs  # direct connection keeps prepared statements

    def test_transaction_pooler_port_disables_prepared_statements(self):
        url, kwargs = engine_config(
            "postgresql://postgres.abcd:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        )
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["connect_args"] == {"prepare_threshold": None}

    def test_session_pooler_keeps_prepared_statements(self):
        # Supavisor session mode supports prepared statements; only transaction
        # mode on port 6543 needs psycopg's prepare cache disabled.
        _, kwargs = engine_config(
            "postgresql://postgres.abcd:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        )
        assert "connect_args" not in kwargs

    def test_pgbouncer_flag_detected_and_stripped(self):
        url, kwargs = engine_config(
            "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres?pgbouncer=true"
        )
        # the non-libpq flag would make psycopg's connect() raise, so it's removed
        assert "pgbouncer" not in url
        assert kwargs["connect_args"] == {"prepare_threshold": None}


def test_every_sqlite_connection_enforces_foreign_keys():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE child ("
            "id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL "
            "REFERENCES parent(id))"
        ))

    # Atomic units of work may stage a child before its parent; validation is
    # deferred to commit so ORM flush ordering is not a correctness contract.
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO child (id, parent_id) VALUES (1, 1)"
        ))
        connection.execute(text("INSERT INTO parent (id) VALUES (1)"))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO child (id, parent_id) VALUES (2, 999)"
            ))


def test_legacy_studio_job_integrity_upgrade_is_additive_and_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE studio_jobs ("
            "id VARCHAR(32) PRIMARY KEY, owner VARCHAR(32) NOT NULL, "
            "action_id VARCHAR(24) NOT NULL, lane VARCHAR(24) NOT NULL, "
            "status VARCHAR(16) NOT NULL, progress FLOAT NOT NULL, "
            "active_design_id VARCHAR(32), source_revision_id VARCHAR(32), "
            "requested_outputs INTEGER NOT NULL, "
            "credits_per_output INTEGER NOT NULL, "
            "completed_outputs INTEGER NOT NULL, "
            "charged_outputs INTEGER NOT NULL, error_code VARCHAR(64), "
            "created_at DATETIME, updated_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO studio_jobs ("
            "id, owner, action_id, lane, status, progress, "
            "requested_outputs, credits_per_output, completed_outputs, "
            "charged_outputs, created_at, updated_at) VALUES ("
            "'job_legacy', 'usr_legacy', 'create', 'instant', 'queued', 0, "
            "1, 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))

    db.Base.metadata.create_all(engine)
    db._apply_additive_migrations(engine)
    db._apply_additive_migrations(engine)

    columns = {
        column["name"] for column in inspect(engine).get_columns("studio_jobs")
    }
    assert {"reservation_kind", "accepted_output_sha256"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT action_id, status, reservation_kind, "
            "accepted_output_sha256 FROM studio_jobs WHERE id = 'job_legacy'"
        )).one() == ("create", "queued", None, None)
        triggers = {
            row[0] for row in connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND name LIKE 'facetta_studio_job_integrity_v1_%'"
            ))
        }
        assert triggers == {
            "facetta_studio_job_integrity_v1_insert",
            "facetta_studio_job_integrity_v1_update",
        }
        evidence = connection.execute(text(
            "SELECT dialect, integrity_mode FROM facetta_schema_migrations "
            "WHERE revision = :revision"
        ), {"revision": db.STUDIO_JOB_INTEGRITY_REVISION}).one()
        assert evidence == ("sqlite", "additive_integrity_triggers")

    invalid_updates = (
        "UPDATE studio_jobs SET reservation_kind = 'provider' "
        "WHERE id = 'job_legacy'",
        "UPDATE studio_jobs SET accepted_output_sha256 = '" + ("a" * 64)
        + "' WHERE id = 'job_legacy'",
        "UPDATE studio_jobs SET action_id = 'factory', status = 'succeeded', "
        "completed_outputs = 1, charged_outputs = 1 "
        "WHERE id = 'job_legacy'",
    )
    for statement in invalid_updates:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(statement))

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE studio_jobs SET action_id = 'factory', "
            "status = 'succeeded', completed_outputs = 1, "
            "charged_outputs = 1, accepted_output_sha256 = :digest "
            "WHERE id = 'job_legacy'"
        ), {"digest": "b" * 64})


def test_concurrent_first_sessions_initialize_sqlite_once(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'concurrent.db'}"
    monkeypatch.setattr(
        db,
        "env_value",
        lambda key, default: database_url,
    )

    real_create_all = db.Base.metadata.create_all
    create_all_calls = 0
    call_count_lock = Lock()

    def slow_create_all(engine):
        nonlocal create_all_calls
        with call_count_lock:
            create_all_calls += 1
        sleep(0.05)
        real_create_all(engine)

    monkeypatch.setattr(db.Base.metadata, "create_all", slow_create_all)
    db._initialize_engine.cache_clear()

    worker_count = 8
    start = Barrier(worker_count)

    def open_first_session(_worker):
        start.wait()
        dependency = db.get_db()
        session = next(dependency)
        try:
            session.execute(select(db.User).limit(1)).all()
            return session.get_bind()
        finally:
            dependency.close()

    engines = []
    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            engines = list(executor.map(open_first_session, range(worker_count)))

        assert create_all_calls == 1
        assert len({id(engine) for engine in engines}) == 1
    finally:
        for engine in {id(item): item for item in engines}.values():
            engine.dispose()
        db._initialize_engine.cache_clear()

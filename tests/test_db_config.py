"""DATABASE_URL normalization and engine configuration.

The point of these is that a connection string copied verbatim from the Supabase
dashboard reaches a working engine — bare scheme routed to psycopg v3, the
transaction pooler's prepared-statement incompatibility handled, and idle-drop
resilience turned on for hosted Postgres.
"""

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

    def test_pooler_host_on_session_port_still_detected(self):
        # session pooler (5432) on the pooler host is still pgbouncer-fronted
        _, kwargs = engine_config(
            "postgresql://postgres.abcd:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        )
        assert kwargs["connect_args"] == {"prepare_threshold": None}

    def test_pgbouncer_flag_detected_and_stripped(self):
        url, kwargs = engine_config(
            "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres?pgbouncer=true"
        )
        # the non-libpq flag would make psycopg's connect() raise, so it's removed
        assert "pgbouncer" not in url
        assert kwargs["connect_args"] == {"prepare_threshold": None}

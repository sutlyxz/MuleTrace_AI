"""Alembic environment: same migrations for local PostgreSQL and Amazon RDS."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from db.config import DATABASE_URL_ENV, get_database_url, redact_url
from db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL from DATABASE_URL, or from the env var named by `-x url_env=NAME`."""
    env_name = context.get_x_argument(as_dictionary=True).get("url_env", DATABASE_URL_ENV)
    return get_database_url(env_name)


def run_migrations_offline() -> None:
    """Emit SQL to stdout (`alembic upgrade head --sql`) — useful for RDS review."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    print(f"Alembic target: {redact_url(url)}")
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

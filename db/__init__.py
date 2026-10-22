"""MuleTrace AI persistence layer (PostgreSQL via SQLAlchemy + Alembic).

Only ``db.config`` and ``db.dataframes`` are safe to import without
SQLAlchemy installed; everything else is imported lazily when the
``postgres`` data backend is selected.
"""

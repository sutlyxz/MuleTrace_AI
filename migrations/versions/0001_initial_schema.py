"""Initial MuleTrace schema: accounts, transactions, cases, case_accounts, alerts.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID = sa.String(64)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("account_id", ID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("account_id", name="pk_accounts"),
    )

    op.create_table(
        "transactions",
        sa.Column("transaction_id", ID, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=False), nullable=False),
        sa.Column("source_account", ID, nullable=False),
        sa.Column("target_account", ID, nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("scenario", ID, server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("is_suspicious", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_transactions_amount_non_negative"),
        sa.ForeignKeyConstraint(["source_account"], ["accounts.account_id"],
                                name="fk_transactions_source_account_accounts"),
        sa.ForeignKeyConstraint(["target_account"], ["accounts.account_id"],
                                name="fk_transactions_target_account_accounts"),
        sa.PrimaryKeyConstraint("transaction_id", name="pk_transactions"),
    )
    op.create_index("ix_transactions_source_ts", "transactions", ["source_account", "timestamp"])
    op.create_index("ix_transactions_target_ts", "transactions", ["target_account", "timestamp"])
    op.create_index("ix_transactions_ts_id", "transactions", ["timestamp", "transaction_id"])

    op.create_table(
        "cases",
        sa.Column("case_id", ID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("case_id", name="pk_cases"),
    )

    op.create_table(
        "case_accounts",
        sa.Column("case_id", ID, nullable=False),
        sa.Column("account_id", ID, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"], ondelete="CASCADE",
                                name="fk_case_accounts_case_id_cases"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"],
                                name="fk_case_accounts_account_id_accounts"),
        sa.PrimaryKeyConstraint("case_id", "account_id", name="pk_case_accounts"),
    )
    op.create_index("ix_case_accounts_account_id", "case_accounts", ["account_id"])

    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(32), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), server_default=sa.text("'new'"), nullable=False),
        sa.Column("source", sa.String(32), server_default=sa.text("'rule_engine'"), nullable=False),
        sa.Column("account_id", ID, nullable=False),
        sa.Column("rule", ID, nullable=False),
        sa.Column("transaction_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("finding", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("alert_id", name="pk_alerts"),
        sa.UniqueConstraint("seq", name="uq_alerts_seq"),
    )
    op.create_index("ix_alerts_account_rule", "alerts", ["account_id", "rule"])
    op.create_index("ix_alerts_status", "alerts", ["status"])

    op.create_table(
        "alert_transactions",
        sa.Column("alert_id", sa.String(32), nullable=False),
        sa.Column("transaction_id", ID, nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.alert_id"], ondelete="CASCADE",
                                name="fk_alert_transactions_alert_id_alerts"),
        sa.PrimaryKeyConstraint("alert_id", "transaction_id", name="pk_alert_transactions"),
    )
    op.create_index("ix_alert_transactions_transaction_id", "alert_transactions", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_transactions_transaction_id", table_name="alert_transactions")
    op.drop_table("alert_transactions")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_account_rule", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_case_accounts_account_id", table_name="case_accounts")
    op.drop_table("case_accounts")
    op.drop_table("cases")
    op.drop_index("ix_transactions_ts_id", table_name="transactions")
    op.drop_index("ix_transactions_target_ts", table_name="transactions")
    op.drop_index("ix_transactions_source_ts", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("accounts")

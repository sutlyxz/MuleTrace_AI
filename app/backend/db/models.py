"""SQLAlchemy 2.0 ORM models — shared by local PostgreSQL and Amazon RDS.

Column names mirror the verified CSV/JSON headers exactly:
  transactions.csv  : transaction_id, timestamp, source_account, target_account,
                      amount, scenario, is_suspicious
  case_accounts.csv : case_id, account_id
  alerts.json       : alert_id, created_at, status, source, account_id, rule,
                      transaction_ids, reason, evidence, finding
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names keep Alembic migrations identical everywhere.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ID_LENGTH = 64


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        Index("ix_transactions_source_ts", "source_account", "timestamp"),
        Index("ix_transactions_target_ts", "target_account", "timestamp"),
        Index("ix_transactions_ts_id", "timestamp", "transaction_id"),
    )

    transaction_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    # Naive timestamp on purpose: CSV times carry no zone; TIMESTAMPTZ would
    # shift them by the server/session zone (Windows +07 vs RDS UTC).
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    source_account: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("accounts.account_id"), nullable=False
    )
    target_account: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("accounts.account_id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    scenario: Mapped[str] = mapped_column(
        String(ID_LENGTH), nullable=False, server_default=text("'unknown'")
    )
    is_suspicious: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Case(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseAccount(Base):
    __tablename__ = "case_accounts"
    __table_args__ = (Index("ix_case_accounts_account_id", "account_id"),)

    case_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("cases.case_id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("accounts.account_id"), primary_key=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Alert(Base):
    """One rule-engine alert. Shape matches an alerts.json entry 1:1.

    No FK to accounts/transactions: alerts are audit records and must survive
    upstream data changes (and tests use synthetic findings).
    """

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_account_rule", "account_id", "rule"),
        Index("ix_alerts_status", "status"),
    )

    alert_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Preserves JSON-list append order for load_alerts().
    seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'new'")
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'rule_engine'")
    )
    account_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    rule: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    transaction_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSONB keeps the original type (float in practice, str in unit tests).
    evidence: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    finding: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AlertTransaction(Base):
    """Relational evidence link so investigators can query tx -> alerts."""

    __tablename__ = "alert_transactions"
    __table_args__ = (Index("ix_alert_transactions_transaction_id", "transaction_id"),)

    alert_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("alerts.alert_id", ondelete="CASCADE"), primary_key=True
    )
    transaction_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)

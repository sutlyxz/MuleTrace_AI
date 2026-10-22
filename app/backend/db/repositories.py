"""Repository layer: the only place that issues SQL for MuleTrace data.

Read methods return the same shapes the CSV/JSON code produced, so callers
(engine tools, alert service, auto scanner) stay unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.backend.db.dataframes import TRANSACTION_COLUMNS, case_accounts_frame, transactions_frame
from app.backend.db.models import Alert, AlertTransaction, CaseAccount, Transaction
from app.backend.db.session import get_engine, session_scope


def _iso_utc(value: datetime | None) -> str | None:
    """Render TIMESTAMPTZ like the original datetime.now(timezone.utc).isoformat()."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class TransactionRepository:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_engine()

    def as_dataframe(self) -> pd.DataFrame:
        """All transactions as a raw frame equivalent to pd.read_csv(transactions.csv)."""
        table = Transaction.__table__
        stmt = select(*[table.c[name] for name in TRANSACTION_COLUMNS]).order_by(
            table.c.timestamp, table.c.transaction_id
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return transactions_frame(rows)

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(Transaction)).scalar_one())

    def change_signature(self) -> tuple:
        """Cheap change detector for the auto scanner (row count + newest ingest time)."""
        with self.engine.connect() as conn:
            count, newest = conn.execute(
                select(func.count(), func.max(Transaction.ingested_at))
            ).one()
        return ("db:transactions", int(count), _iso_utc(newest))


class CaseRepository:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_engine()

    def as_dataframe(self) -> pd.DataFrame:
        """Case/account links as a frame equivalent to pd.read_csv(case_accounts.csv)."""
        stmt = select(CaseAccount.case_id, CaseAccount.account_id).order_by(
            CaseAccount.case_id, CaseAccount.account_id
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return case_accounts_frame(rows)

    def change_signature(self) -> tuple:
        with self.engine.connect() as conn:
            count, newest = conn.execute(
                select(func.count(), func.max(CaseAccount.ingested_at))
            ).one()
        return ("db:case_accounts", int(count), _iso_utc(newest))


class AlertRepository:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_engine()

    @staticmethod
    def _to_dict(alert: Alert) -> dict[str, Any]:
        # Key order mirrors alerts.json entries.
        return {
            "alert_id": alert.alert_id,
            "created_at": _iso_utc(alert.created_at),
            "status": alert.status,
            "source": alert.source,
            "account_id": alert.account_id,
            "rule": alert.rule,
            "transaction_ids": list(alert.transaction_ids or []),
            "reason": alert.reason,
            "evidence": alert.evidence,
            "finding": alert.finding,
        }

    def list_alerts(self) -> list[dict[str, Any]]:
        """All alerts in original append order (same as the JSON list)."""
        with session_scope(self.engine) as session:
            alerts = session.scalars(select(Alert).order_by(Alert.seq)).all()
            return [self._to_dict(alert) for alert in alerts]

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(Alert)).scalar_one())

    def insert_many(self, alerts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert alerts in order; skip IDs that already exist (race-safe dedupe).

        Returns only the alerts actually inserted by this call.
        """
        inserted: list[dict[str, Any]] = []
        with session_scope(self.engine) as session:
            for alert in alerts:
                tx_ids = [str(tx) for tx in alert.get("transaction_ids") or []]
                stmt = (
                    pg_insert(Alert.__table__)
                    .values(
                        alert_id=alert["alert_id"],
                        created_at=_parse_created_at(alert.get("created_at")),
                        status=alert.get("status") or "new",
                        source=alert.get("source") or "rule_engine",
                        account_id=str(alert.get("account_id") or ""),
                        rule=str(alert.get("rule") or ""),
                        transaction_ids=tx_ids,
                        reason=alert.get("reason"),
                        evidence=alert.get("evidence"),
                        finding=alert.get("finding") or {},
                    )
                    .on_conflict_do_nothing(index_elements=["alert_id"])
                    .returning(Alert.__table__.c.alert_id)
                )
                if session.execute(stmt).scalar_one_or_none() is None:
                    continue
                if tx_ids:
                    session.execute(
                        pg_insert(AlertTransaction.__table__)
                        .values([
                            {"alert_id": alert["alert_id"], "transaction_id": tx}
                            for tx in dict.fromkeys(tx_ids)
                        ])
                        .on_conflict_do_nothing()
                    )
                inserted.append(alert)
        return inserted

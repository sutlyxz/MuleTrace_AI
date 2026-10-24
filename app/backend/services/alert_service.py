"""Persistent, evidence-linked risk alerts derived from engine.detect_risk().

Storage backend follows MULETRACE_DATA_BACKEND:
  csv       -> app/data/alerts.json (atomic file writes, original behaviour)
  postgres  -> alerts / alert_transactions tables via DATABASE_URL
Passing an explicit ``path`` always uses that JSON file (tests rely on this).
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import os
import tempfile

from app.backend.db.config import data_backend, get_alerts_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALERTS_FILE = PROJECT_ROOT / 'data' / 'alerts.json'
ALERTS_DEMO_FILE = ALERTS_FILE  # retained alias for backward-compatibility
DATABASE_LOCATION = 'postgresql:alerts'


def _resolve_alert_path(path: Path | str | None = None) -> Path:
    if path is None:
        return ALERTS_FILE
    return Path(path)


def _ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = str(value).split(',')
    return sorted({str(item).strip() for item in items if str(item).strip()})


def alert_id(finding: dict[str, Any]) -> str:
    """Stable ID for one account/rule/evidence set, regardless of row order."""
    identity = {
        'account_id': str(finding.get('account_id') or '').strip(),
        'rule': str(finding.get('rule') or '').strip(),
        'transaction_ids': _ids(finding.get('transaction_ids')),
    }
    # Some rules (e.g. case overlap) have no transaction IDs. Include evidence
    # to avoid accidentally collapsing distinct case-link findings.
    if not identity['transaction_ids']:
        identity['evidence'] = str(finding.get('evidence') or '')
        identity['reason'] = str(finding.get('reason') or '')
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    return 'ALT-' + sha256(encoded.encode('utf-8')).hexdigest()[:16].upper()


def _use_database(path: Path | str | None = None) -> bool:
    """DB only for the canonical alert store; an explicit custom path means JSON."""
    if data_backend() != 'postgres':
        return False
    return _resolve_alert_path(path) == ALERTS_FILE


def load_alerts(path: Path | str | None = None) -> list[dict[str, Any]]:
    resolved = _resolve_alert_path(path)
    if _use_database(resolved):
        from app.backend.db.repositories import AlertRepository  # lazy: optional dependency
        return AlertRepository().list_alerts()
    if not resolved.exists():
        return []
    with resolved.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError(f'{resolved.name} must contain a JSON list of alert objects')
    return data


def _save_atomic(path: Path, alerts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.alerts-', suffix='.tmp', delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(alerts, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def scan_risk_alerts(path: Path | str | None = None) -> dict[str, Any]:
    """Call existing risk engine and append only unseen rule findings.

    Returns a summary for a scanner, API or demo. No AI-generated alerts here.
    """
    from ..engine import detect_risk  # import lazily; keeps unit tests independent

    resolved = _resolve_alert_path(path)
    result = detect_risk()
    findings = result.get('findings', [])
    if not isinstance(findings, list):
        raise ValueError('detect_risk() must return findings as a list')

    alerts = load_alerts(resolved)
    existing_ids = {item.get('alert_id') for item in alerts}
    now = datetime.now(timezone.utc).isoformat()
    created = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError('Risk finding must be a dictionary')
        identifier = alert_id(finding)
        if identifier in existing_ids:
            continue
        alert = {
            'alert_id': identifier,
            'created_at': now,
            'status': 'new',
            'source': 'rule_engine',
            'account_id': str(finding.get('account_id') or ''),
            'rule': str(finding.get('rule') or ''),
            'transaction_ids': _ids(
                finding.get('transaction_ids')
                or [
                    finding.get('incoming_transaction_id') or '',
                    finding.get('outgoing_transaction_id') or '',
                ]
            ),
            'reason': finding.get('reason'),
            'evidence': finding.get('evidence'),
            'finding': finding,  # retain original engine evidence for backend/AI
        }
        alerts.append(alert)
        created.append(alert)
        existing_ids.add(identifier)

    if created:
        if _use_database(resolved):
            from app.backend.db.repositories import AlertRepository
            # ON CONFLICT(alert_id) DO NOTHING: a concurrent scanner may have
            # inserted the same alert; report only rows this call inserted.
            # (Skipped rows already exist in the table, so the total is unchanged.)
            inserted_ids = {item['alert_id'] for item in AlertRepository().insert_many(created)}
            created = [item for item in created if item['alert_id'] in inserted_ids]
        else:
            _save_atomic(resolved, alerts)
    return {
        'finding_count': len(findings),
        'new_alert_count': len(created),
        'total_alert_count': len(alerts),
        'new_alerts': created,
        'alerts_file': DATABASE_LOCATION if _use_database(resolved) else str(resolved),
    }

"""Persistent, evidence-linked risk alerts derived from engine.detect_risk()."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import os
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALERTS_FILE = PROJECT_ROOT / 'data' / 'alerts.json'


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


def load_alerts(path: Path = ALERTS_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError('alerts.json must contain a JSON list of alert objects')
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


def scan_risk_alerts(path: Path = ALERTS_FILE) -> dict[str, Any]:
    """Call existing risk engine and append only unseen rule findings.

    Returns a summary for a scanner, API or demo. No AI-generated alerts here.
    """
    from ..engine import detect_risk  # import lazily; keeps unit tests independent

    result = detect_risk()
    findings = result.get('findings', [])
    if not isinstance(findings, list):
        raise ValueError('detect_risk() must return findings as a list')

    alerts = load_alerts(path)
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
        _save_atomic(path, alerts)
    return {
        'finding_count': len(findings),
        'new_alert_count': len(created),
        'total_alert_count': len(alerts),
        'new_alerts': created,
        'alerts_file': str(path),
    }

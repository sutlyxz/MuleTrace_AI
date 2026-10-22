"""Watch the demo data (CSV files or PostgreSQL) for changes and trigger rule-based alerts."""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from db.config import data_backend
from investigation.alert_service import PROJECT_ROOT, scan_risk_alerts

WATCHED_FILES = (
    PROJECT_ROOT / 'data' / 'transactions.csv',
    PROJECT_ROOT / 'data' / 'case_accounts.csv',
)


def _scan_errors() -> tuple[type[BaseException], ...]:
    errors: tuple[type[BaseException], ...] = (OSError, ValueError, ImportError, RuntimeError)
    try:
        from sqlalchemy.exc import SQLAlchemyError
    except ImportError:
        return errors
    return errors + (SQLAlchemyError,)


def _database_signature() -> tuple:
    """Row count + newest ingest time per table (DB has no file mtimes)."""
    from db.repositories import CaseRepository, TransactionRepository
    return (TransactionRepository().change_signature(), CaseRepository().change_signature())


def signature(paths: tuple[Path, ...] = WATCHED_FILES) -> tuple:
    """Track both transaction and case-link changes (size + nanosecond mtime)."""
    if paths == WATCHED_FILES and data_backend() == 'postgres':
        return _database_signature()
    result = []
    for path in paths:
        if not path.exists():
            result.append((str(path), None, None))
        else:
            stat = path.stat()
            result.append((str(path), stat.st_size, stat.st_mtime_ns))
    return tuple(result)


def main() -> None:
    parser = argparse.ArgumentParser(description='MuleTrace automatic rule-alert scanner')
    parser.add_argument('--interval', type=float, default=3.0,
                        help='Seconds between checks (default: 3)')
    parser.add_argument('--once', action='store_true', help='Scan once and exit')
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('--interval must be greater than zero')

    last_signature = None
    scan_errors = _scan_errors()
    print(f'MuleTrace Auto Alert scanner started [backend={data_backend()}] (Ctrl+C to stop)', flush=True)
    try:
        while True:
            try:
                current = signature()
            except scan_errors as exc:
                print(f'[SCAN ERROR] {exc}', flush=True)
                current = None  # force a retry on the next interval
            if current is not None and current != last_signature:
                try:
                    result = scan_risk_alerts()
                except scan_errors as exc:
                    print(f'[SCAN ERROR] {exc}', flush=True)
                    # Retry after next interval even if data has not changed.
                else:
                    last_signature = current
                    print(f"[SCAN] findings={result['finding_count']} "
                          f"new_alerts={result['new_alert_count']} "
                          f"total_alerts={result['total_alert_count']}", flush=True)
                    for alert in result['new_alerts']:
                        print(f"  [NEW] {alert['alert_id']} | {alert['account_id']} "
                              f"| {alert['rule']} | tx={','.join(alert['transaction_ids'])}",
                              flush=True)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\nScanner stopped.', flush=True)


if __name__ == '__main__':
    main()

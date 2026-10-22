"""Watch the demo CSV files for changes and trigger rule-based alerts."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import time

from ..services.alert_service import PROJECT_ROOT, scan_risk_alerts

WATCHED_FILES = (
    PROJECT_ROOT / 'data' / 'transactions.csv',
    PROJECT_ROOT / 'data' / 'case_accounts.csv',
)


def signature(paths: tuple[Path, ...] = WATCHED_FILES) -> tuple:
    """Track both transaction and case-link changes (size + nanosecond mtime)."""
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
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error('--interval must be a positive finite number')

    last_signature = None
    print('MuleTrace Auto Alert scanner started (Ctrl+C to stop)', flush=True)
    try:
        while True:
            current = signature()
            if current != last_signature:
                try:
                    result = scan_risk_alerts()
                except (OSError, ValueError, ImportError) as exc:
                    print(f'[SCAN ERROR] {exc}', flush=True)
                    # Retry after next interval even if CSV has not changed.
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

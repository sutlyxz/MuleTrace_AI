# MuleTrace AI — PostgreSQL / Amazon RDS

The engine can read data from the original CSV files (default) or from
PostgreSQL. The **same** SQLAlchemy models and Alembic migrations are used for
local PostgreSQL and Amazon RDS for PostgreSQL.

## Configuration

| Variable | Purpose |
|---|---|
| `MULETRACE_DATA_BACKEND` | `csv` (default) or `postgres` |
| `DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@HOST:5432/muletrace` |
| `TEST_DATABASE_URL` | Optional disposable DB for integration tests (name must contain `test`) |

Copy `.env.example` to `.env` (git-ignored) and fill in real values.
Never commit `.env`, passwords or AWS credentials.

## Local setup (Windows, PostgreSQL 18)

```powershell
python -m pip install -r requirements.txt
copy .env.example .env        # then edit DATABASE_URL in .env
alembic upgrade head          # create tables (writes to DATABASE_URL)
python -m db.seed --dry-run   # preview: nothing is written
python -m db.seed             # import CSVs (idempotent, insert-only)
python -m db.seed --with-alerts   # optionally import data/alerts.json
```

Then set `MULETRACE_DATA_BACKEND=postgres` in `.env` and verify:

```powershell
python engine.py                              # health check + finding count
python -m investigation.auto_scanner --once   # alert scan into the alerts table
```

## Schema

| Table | Key | Notes |
|---|---|---|
| `accounts` | `account_id` | Union of accounts seen in transactions, case links, accounts.csv |
| `transactions` | `transaction_id` | FK source/target → accounts; `timestamp` is naive (no TZ shift) |
| `cases` | `case_id` | |
| `case_accounts` | (`case_id`, `account_id`) | M:N, FKs to cases and accounts |
| `alerts` | `alert_id` | Same fields as alerts.json; `seq` keeps append order |
| `alert_transactions` | (`alert_id`, `transaction_id`) | Evidence links for tx → alert queries |

Alert IDs, evidence transaction IDs and the dedupe logic are unchanged
(`investigation/alert_service.py`). In the database, `alerts.alert_id` is
also the primary key with `ON CONFLICT DO NOTHING`, so concurrent scanners
cannot create duplicates.

## Tests

```powershell
python -m unittest discover -s tests -v        # DB tests auto-skip without TEST_DATABASE_URL
$env:TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/muletrace_test"
python -m unittest tests.test_db_postgres -v   # drops/recreates tables in muletrace_test only
```

`tests/test_db_offline.py` needs no server: it checks every AI tool returns
byte-identical output and alert IDs in csv vs postgres mode.

## Deploying to Amazon RDS for PostgreSQL

1. Create an RDS PostgreSQL instance (private subnet; security group allows
   5432 only from the app/Lambda/EC2 security group).
2. Create a least-privilege app user and database `muletrace`.
3. Store the URL in AWS Secrets Manager / SSM Parameter Store and inject it as
   `DATABASE_URL` — RDS requires TLS, so append `?sslmode=require`
   (or `sslmode=verify-full&sslrootcert=<rds-ca-bundle.pem>`).
4. From a host that can reach RDS:
   ```bash
   alembic upgrade head --sql > rds_schema.sql   # optional: review DDL first
   alembic upgrade head
   python -m db.seed --dry-run && python -m db.seed
   ```
5. Set `MULETRACE_DATA_BACKEND=postgres` for the deployed engine.

No code changes are needed between local and RDS — only `DATABASE_URL`.

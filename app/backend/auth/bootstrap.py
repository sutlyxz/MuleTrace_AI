"""Restricted CLI Bootstrap script to initialize the first Administrator account.

Usage (CMD):
    python -m app.backend.auth.bootstrap

Requirements:
    - Interactive execution only (prompts for email, display name, and hidden password).
    - Checks for existing active administrators; aborts if an admin already exists.
    - Validates strong password policy.
    - Stores password strictly as an Argon2id hash.
    - No hardcoded passwords or default accounts.
"""
from __future__ import annotations

import getpass
import sys
from typing import Optional

from sqlalchemy.engine import Engine

from app.backend.auth.security import (
    hash_password,
    normalize_email,
    validate_email_format,
    validate_password_policy,
)
from app.backend.db.auth_repositories import AuditLogRepository, UserRepository
from app.backend.db.session import get_engine, session_scope


def bootstrap_admin(
    engine: Optional[Engine] = None,
    interactive: bool = True,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    password: Optional[str] = None,
) -> bool:
    """Bootstrap the very first administrator account in PostgreSQL.

    Rejects execution if an administrator account already exists.
    """
    resolved_engine = engine or get_engine()

    with session_scope(resolved_engine) as session:
        user_repo = UserRepository(session)
        audit_repo = AuditLogRepository(session)

        # 1. Safety check: Reject duplicate bootstrap attempts
        admin_count = user_repo.count_admins()
        if admin_count > 0:
            print("\n[ERROR] An active Administrator account already exists.")
            print("[SECURITY] Bootstrap is strictly forbidden when an administrator is already provisioned.")
            return False

        if interactive:
            print("\n" + "=" * 60)
            print(" MuleTrace AI — First Administrator Account Bootstrap")
            print("=" * 60)
            print("This tool creates the initial Administrator account.")
            print("Only ONE administrator bootstrap is allowed.\n")

            while True:
                raw_email = input("Enter Administrator Email: ").strip()
                if not validate_email_format(raw_email):
                    print("  [!] Invalid email format. Example: admin@agency.go.th")
                    continue
                norm_email = normalize_email(raw_email)
                if user_repo.get_by_email(norm_email) is not None:
                    print(f"  [!] User with email '{norm_email}' already exists.")
                    continue
                break

            while True:
                raw_name = input("Enter Display Name: ").strip()
                if not raw_name:
                    print("  [!] Display name cannot be empty.")
                    continue
                break

            while True:
                pwd1 = getpass.getpass("Enter Password (hidden): ")
                valid, msg = validate_password_policy(pwd1)
                if not valid:
                    print(f"  [!] {msg}")
                    continue
                pwd2 = getpass.getpass("Confirm Password (hidden): ")
                if pwd1 != pwd2:
                    print("  [!] Passwords do not match. Please try again.")
                    continue
                break

            email = norm_email
            display_name = raw_name
            password = pwd1
        else:
            if not email or not display_name or not password:
                raise ValueError("Email, display_name, and password are required for non-interactive bootstrap.")
            if not validate_email_format(email):
                raise ValueError("Invalid email format.")
            valid, msg = validate_password_policy(password)
            if not valid:
                raise ValueError(msg)
            email = normalize_email(email)
            if user_repo.get_by_email(email) is not None:
                raise ValueError(f"User with email '{email}' already exists.")

        # 2. Hash password with Argon2id and create user
        pwd_hash = hash_password(password)
        admin_user = user_repo.create_user(
            email=email,
            display_name=display_name,
            role="admin",
            password_hash=pwd_hash,
            is_active=True,
            must_change_password=False,
        )

        # 3. Log immutable audit trail
        audit_repo.log(
            action="admin_bootstrap",
            actor_user_id=admin_user.id,
            target_user_id=admin_user.id,
            safe_metadata={"email": email, "role": "admin"},
        )

        print("\n[SUCCESS] Administrator account provisioned successfully.")
        print(f"User ID: {admin_user.id}")
        print(f"Email:   {admin_user.email}")
        print(f"Role:    {admin_user.role}")
        return True


def main() -> None:
    try:
        success = bootstrap_admin(interactive=True)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[ABORTED] Administrator bootstrap cancelled by operator.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FATAL] Bootstrap failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""DramaClaw Seed Admin User Script.

Creates or updates local admin user credentials in the SQLite user database:
  - Username: AnsoATC
  - Email:    ansoatc@gmail.com
  - Password: Anso@1234
  - Role:     admin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from novelvideo.user_store import seed_user, get_users_db_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed DramaClaw Local Admin User Account")
    parser.add_argument("--username", default="AnsoATC", help="Admin username (default: AnsoATC)")
    parser.add_argument("--email", default="ansoatc@gmail.com", help="Admin email (default: ansoatc@gmail.com)")
    parser.add_argument("--password", default="Anso@1234", help="Admin password (default: Anso@1234)")
    parser.add_argument("--role", default="admin", help="User role (default: admin)")
    args = parser.parse_args()

    user = seed_user(
        username=args.username,
        email=args.email,
        password=args.password,
        role=args.role,
    )

    db_path = get_users_db_path()
    print("===============================================================")
    print("          D R A M A C L A W   A D M I N   S E E D E R")
    print("===============================================================")
    print(f" [✓] User Database:  {db_path}")
    print(f" [✓] User ID:        {user['id']}")
    print(f" [✓] Username:       {user['username']}")
    print(f" [✓] Email:          {user['email']}")
    print(f" [✓] Role:           {user['role']}")
    print(" [✓] Account Status: Active & Ready for Login")
    print("===============================================================\n")


if __name__ == "__main__":
    main()

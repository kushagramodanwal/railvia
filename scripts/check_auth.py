"""Verify the two users and their roles once you have created them.

    .venv/bin/python scripts/check_auth.py

Checks, in order:
  * the API can reach Supabase
  * SUPABASE_JWT_SECRET is set, so sign-ins can be verified
  * both roles exist in `profiles`
  * exactly one head, which is the point of the split

It never asks for a password and never signs anyone in.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.ingest.railradar import load_dotenv  # noqa: E402
from src.store.auth import JWT_SECRET_VAR, jwks_url  # noqa: E402

OK, BAD, WARN = "  OK  ", " FAIL ", " WARN "


def main() -> int:
    load_dotenv()
    problems = 0

    try:
        from src.store.supabase_store import SupabaseStore

        store = SupabaseStore()
        print(f"[{OK}] Supabase reachable")
    except Exception as exc:  # noqa: BLE001
        print(f"[{BAD}] Supabase unreachable: {exc}")
        return 1

    # Current Supabase projects sign with asymmetric keys and need no shared
    # secret at all; only legacy projects use SUPABASE_JWT_SECRET.
    import json
    import urllib.request

    verified = False
    url = jwks_url()
    if url:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                keys = json.loads(r.read()).get("keys", [])
            if keys:
                algs = ", ".join(sorted({k.get("alg", "?") for k in keys}))
                print(f"[{OK}] sign-ins verified against the project's public "
                      f"keys ({algs})")
                print("        No shared secret needed — SUPABASE_JWT_SECRET "
                      "is ignored.")
                verified = True
        except Exception as exc:  # noqa: BLE001
            print(f"[{WARN}] could not reach the JWKS endpoint: {exc}")

    if not verified:
        if os.environ.get(JWT_SECRET_VAR):
            print(f"[{OK}] {JWT_SECRET_VAR} is set — legacy HS256 verification")
        else:
            problems += 1
            print(f"[{BAD}] no way to verify sign-ins")
            print("        Check SUPABASE_URL is correct, or set "
                  f"{JWT_SECRET_VAR} for a legacy project.")

    # IMPORTANT: this reads with the anon key, and the "read own profile"
    # policy restricts rows to auth.uid() = id. Anonymously that matches
    # nothing, so an empty result proves nothing at all — it does NOT mean
    # there are no users. Only the SQL editor (which bypasses RLS) can answer
    # that, so we say so rather than reporting a false failure.
    try:
        rows = (store.client.table("profiles")
                .select("id, role, full_name, department").execute().data) or []
    except Exception as exc:  # noqa: BLE001
        print(f"[{BAD}] cannot read profiles: {exc}")
        return 1

    if not rows:
        print(f"[{WARN}] cannot see any profiles from here")
        print("        Expected: row-level security only shows a user their")
        print("        own profile, and this check is not signed in. It")
        print("        cannot tell whether your users exist.")
        print("        Run this in the Supabase SQL editor to find out:")
        print()
        print("          select u.email, p.role, p.full_name")
        print("            from auth.users u")
        print("            left join public.profiles p on p.id = u.id;")
        print()
        print("        A user with a NULL role means the profiles trigger did")
        print("        not fire — usually because the account was created")
        print("        before schema.sql was run. Fix with:")
        print()
        print("          insert into public.profiles (id, role)")
        print("          select id, 'engineer' from auth.users")
        print("           where id not in (select id from public.profiles);")
        print()
        return 1 if problems else 0

    heads = [r for r in rows if r["role"] == "head"]
    engineers = [r for r in rows if r["role"] == "engineer"]
    print(f"[{OK}] {len(rows)} user(s) in profiles")
    for r in rows:
        name = r.get("full_name") or "(no name)"
        dept = f" · {r['department']}" if r.get("department") else ""
        print(f"        {r['role']:9} {name}{dept}")

    if not heads:
        problems += 1
        print(f"[{BAD}] nobody has the head role — nobody can grant a closure")
        print("        Run the promote SQL at the bottom of src/store/schema.sql")
    elif len(heads) > 1:
        print(f"[{WARN}] {len(heads)} heads. Not wrong, but the whole point of "
              "the split is that granting a closure is one person's call.")
    if not engineers:
        print(f"[{WARN}] no engineer account — you cannot demonstrate a refusal")

    print()
    if problems:
        print(f"{problems} thing(s) still to fix.")
        return 1
    print("Ready. Sign in at http://localhost:3000 as each user:")
    print("  head     — Approve and Mark done both work")
    print("  engineer — Mark done works; Approve is refused by Postgres, not "
          "just greyed out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

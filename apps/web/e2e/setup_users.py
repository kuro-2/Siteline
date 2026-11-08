"""Create e2e users in the LOCAL Supabase (password login for tests only) and print JSON."""
import json
import sys

import httpx

from engine.db import connect
from engine.settings import get_settings

s = get_settings()
if "127.0.0.1" not in s.supabase_url and "localhost" not in s.supabase_url:
    sys.exit("Refusing to create test users outside a local Supabase.")
key = s.supabase_service_role_key
headers = {"apikey": key, "Authorization": f"Bearer {key}"}
out = {}
for role in ("resident", "analyst"):
    email = f"e2e-{role}@example.test"
    password = "e2e-password-123"
    with connect() as conn:
        row = conn.execute("select id from auth.users where email = %s", (email,)).fetchone()
        if row:
            conn.execute("delete from survey_responses where respondent_id = %s", (row["id"],))
            conn.execute("delete from auth.users where id = %s", (row["id"],))
    r = httpx.post(f"{s.supabase_url}/auth/v1/admin/users", headers=headers,
                   json={"email": email, "password": password, "email_confirm": True})
    r.raise_for_status()
    uid = r.json()["id"]
    with connect() as conn:
        conn.execute(
            "update profiles set role = %s, display_name = %s, verified_at = now() where id = %s",
            ("public" if role == "resident" else "analyst", f"E2E {role.title()}", uid),
        )
    out[role] = {"email": email, "password": password}
print(json.dumps(out))

"""
A deliberately buggy FastAPI user endpoint module.

This file is the subject of the dogfood experiment (dogfood_honest.py). It
contains exactly 14 known, specific bugs. The experiment measures how many of
them an LLM reviewer finds, with and without a code-review skill injected.

DO NOT FIX THESE BUGS. They are the ground truth for the experiment. The 14
bugs are catalogued in dogfood_honest.py (BUGS).
"""

import sqlite3

from fastapi import FastAPI

app = FastAPI()

# Bug 5: hardcoded database connection string with credentials (security leak)
DB_CONNECTION = "postgresql://admin:SuperSecret123@prod-db.internal:5432/users"


# Bug 9: wrong HTTP method (a read should be GET, not POST)
# Bug 6: no authentication on the endpoint
# Bug 7: no rate limiting on the endpoint
# Bug 10: no response_model declared
@app.post("/users/{user_id}")
def get_user(user_id: int):
    # Bug 8: no request logging
    # Bug 4: no validation that user_id is non-negative
    # Bug 12: connection is opened but never closed (no cleanup / context manager)
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # Bug 2: SQL injection — f-string interpolation instead of parameterized query
    query = f"SELECT id, username, email, password_hash FROM users WHERE id = {user_id}"

    # Bug 3: no try/except around the database call
    cursor.execute(query)
    row = cursor.fetchone()

    # Bug 1: Optional is used but never imported (from typing import Optional)
    user: Optional[dict] = None
    if row:
        # Bug 14: returns the password hash in the response (sensitive data exposure)
        user = {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "password_hash": row[3],
        }
    return user


# Bug 11: no CORS configuration anywhere in the app
# Bug 13: list endpoint has no pagination (no limit / offset)
@app.get("/users")
def list_users():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, password_hash FROM users")
    rows = cursor.fetchall()
    return [
        {
            "id": r[0],
            "username": r[1],
            "email": r[2],
            "password_hash": r[3],
        }
        for r in rows
    ]

"""Test tasks for the target repo. Each task is a coding instruction."""
TASKS = [
    {
        "id": "task-1",
        "description": "Add a GET /users/{user_id} endpoint that returns a single user by ID, or 404 if not found",
        "assertion": "GET /users/1 returns 200 with user data; GET /users/999 returns 404"
    },
    {
        "id": "task-2",
        "description": "Add a DELETE /users/{user_id} endpoint that removes a user and returns 204, or 404 if not found",
        "assertion": "DELETE /users/1 returns 204; GET /users/1 returns 404 afterwards"
    },
    {
        "id": "task-3",
        "description": "Add email validation to UserCreate — reject invalid emails with 422",
        "assertion": "POST /users with email 'not-email' returns 422; valid email succeeds"
    },
    {
        "id": "task-4",
        "description": "Add a PUT /users/{user_id} endpoint to update user name/email, returning 404 if not found",
        "assertion": "PUT /users/1 updates name; PUT /users/999 returns 404"
    },
    {
        "id": "task-5",
        "description": "Add a /health endpoint that returns {status: 'ok', user_count: N}",
        "assertion": "GET /health returns 200 with status and user_count fields"
    }
]

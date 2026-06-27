"""Target FastAPI app for Yunaki Skills demo"""
from fastapi import FastAPI, Depends
from pydantic import BaseModel

app = FastAPI(title="User Service")


# ─── Schemas ────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: str


# ─── Fake DB ───────────────────────────────────────────────────────────────

_db: list[dict] = []
_next_id = 1


def get_db():
    return _db


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "User Service"}


@app.post("/users", response_model=UserResponse)
def create_user(user: UserCreate, db=Depends(get_db)):
    global _next_id
    new_user = {"id": _next_id, **user.model_dump()}
    _next_id += 1
    db.append(new_user)
    return new_user


@app.get("/users", response_model=list[UserResponse])
def list_users(db=Depends(get_db)):
    return db

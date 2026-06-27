"""Target FastAPI app for Yunaki Skills demo"""
from fastapi import FastAPI, Depends, HTTPException, Response
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


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db=Depends(get_db)):
    for user in db:
        if user["id"] == user_id:
            return user
    raise HTTPException(status_code=404, detail="User not found")


@app.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db=Depends(get_db)):
    found_user_index = -1
    for i, user in enumerate(db):
        if user["id"] == user_id:
            found_user_index = i
            break

    if found_user_index != -1:
        del db[found_user_index]
        return Response(status_code=204)
    else:
        raise HTTPException(status_code=404, detail="User not found")


@app.get("/health")
def health_check(db=Depends(get_db)):
    return {"status": "ok", "user_count": len(db)}

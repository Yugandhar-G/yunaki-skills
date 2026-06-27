"""Load configuration from .env file"""

import os
from pathlib import Path

from dotenv import load_dotenv

_load_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_load_env_path)


def get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


_DEFAULT_CLUSTER = "cluster0.8csxzc.mongodb.net"


def build_mongo_uri() -> str:
    """Build a usable MongoDB connection URI.

    Prefers MONGODB_URI as-is, but if it carries a redacted password
    placeholder ("***@") reconstructs it from MONGODB_USER / MONGODB_PASS /
    MONGODB_CLUSTER. Falls back to a localhost URI when nothing is configured.
    """
    uri = get("MONGODB_URI")
    user = get("MONGODB_USER")
    password = get("MONGODB_PASS")
    cluster = get("MONGODB_CLUSTER", _DEFAULT_CLUSTER)

    needs_rebuild = (not uri) or ("***@" in uri)
    if needs_rebuild and user and password:
        return f"mongodb+srv://{user}:{password}@{cluster}/yunaki?appName=Cluster0"
    if uri:
        return uri
    return "mongodb://localhost:27017"

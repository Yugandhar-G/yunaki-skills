# Yunaki Skills — application image
# Python 3.11 slim, installs deps, copies source + dashboard, runs uvicorn.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps kept minimal. curl is handy for debugging health from inside the
# container; the compose healthcheck itself uses Python (no curl dependency).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Project metadata + source. Installed editable so `yunaki_skills` is importable
# from the configured src/ layout (see pyproject.toml).
COPY pyproject.toml ./
COPY src/ ./src/
COPY dashboard/ ./dashboard/
COPY skills/ ./skills/
RUN pip install -e .

EXPOSE 8000

# Default command. Host 0.0.0.0 so the port is reachable outside the container.
CMD ["uvicorn", "yunaki_skills.main:app", "--host", "0.0.0.0", "--port", "8000"]

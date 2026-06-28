# Yunaki Skills — application image
# Python 3.11 slim, installs deps, copies source + dashboard, runs uvicorn.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python dependencies first for better layer caching. Deps are kept
# light on purpose (no torch/sentence-transformers/numpy) so the build stays
# small and fast; the app falls back to deterministic hash embeddings when the
# optional embeddings extra isn't installed.
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Seed skills are loaded at runtime by main.py, so they must be in the image.
# Copy them before installing the package so the layer is in place.
COPY skills/ ./skills/

# Project metadata + source. Installed editable so `yunaki_skills` is importable
# from the configured src/ layout (see pyproject.toml).
COPY pyproject.toml ./
COPY src/ ./src/
COPY dashboard/ ./dashboard/
RUN pip install -e .

EXPOSE 8000

# Default command. Host 0.0.0.0 so the port is reachable outside the container.
CMD ["uvicorn", "yunaki_skills.main:app", "--host", "0.0.0.0", "--port", "8000"]

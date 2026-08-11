# syntax=docker/dockerfile:1.7
FROM python:3.12.7-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app/src
WORKDIR /app

RUN addgroup --system dataguard && adduser --system --ingroup dataguard --home /nonexistent dataguard
COPY requirements/runtime-linux.lock /tmp/runtime-linux.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/runtime-linux.lock
COPY src ./src
COPY data ./data
COPY docs/contracts ./docs/contracts
RUN mkdir -p /app/artifacts /tmp/dataguard && chown -R dataguard:dataguard /app/artifacts /tmp/dataguard

USER dataguard
EXPOSE 8000
CMD ["python", "-m", "dataguard.server"]

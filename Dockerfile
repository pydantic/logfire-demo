FROM python:3.12-slim AS build

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libssl-dev \
    libffi-dev \
    protobuf-compiler \
    gcc \
    musl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock ./

ENV UV_COMPILE_BYTECODE=1

RUN uv sync --locked --no-install-project --no-dev

COPY ./src /app/src

ARG LOGFIRE_TOKEN
ENV LOGFIRE_TOKEN=$LOGFIRE_TOKEN

FROM python:3.12-slim AS main

COPY --from=build --chown=app:app /app /app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "src"]

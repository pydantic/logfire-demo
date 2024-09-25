FROM python:3.12-alpine AS build

WORKDIR /app

# required for logfire[system-metrics] which in turn requires psutlils
RUN apk add --no-cache gcc musl-dev linux-headers && rm -rf /var/cache/apk/*

RUN pip install uv

COPY pyproject.toml uv.lock ./

ENV UV_COMPILE_BYTECODE=1

RUN uv sync --locked --no-install-project --no-dev

COPY ./src /app/src

ARG LOGFIRE_TOKEN
ENV LOGFIRE_TOKEN=$LOGFIRE_TOKEN

FROM python:3.12-alpine AS base

COPY --from=build --chown=app:app /app /app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

FROM base AS webui

CMD ["python", "-m", "src", "webui"]

FROM base AS worker

CMD ["python", "-m", "src", "worker"]

FROM base AS tiling

CMD ["python", "-m", "src", "tiling"]

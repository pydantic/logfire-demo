FROM python:3.12-alpine as base

WORKDIR /app

# required for logfire[system-metrics] which in turn requires psutlils
RUN apk add --no-cache gcc musl-dev linux-headers && rm -rf /var/cache/apk/*

RUN pip install uv

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-install-project --no-dev

COPY ./src /app/src

ARG LOGFIRE_TOKEN
ENV LOGFIRE_TOKEN=$LOGFIRE_TOKEN

ENV PATH="/app/.venv/bin:$PATH"

FROM base AS webui

CMD ["python", "-m", "src", "webui"]

FROM base AS worker

CMD ["python", "-m", "src", "worker"]

FROM base AS tiling

CMD ["python", "-m", "src", "tiling"]

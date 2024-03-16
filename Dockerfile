FROM python:3.12-alpine

WORKDIR /app

RUN pip install uv

COPY ./requirements.lock /app
# https://github.com/astral-sh/rye/discussions/239#discussioncomment-8672119
RUN sed '/^-e/d' requirements.lock > requirements.txt

RUN uv pip install --system -r requirements.txt

COPY ./src /app/src

ARG LOGFIRE_TOKEN
ENV LOGFIRE_TOKEN=$LOGFIRE_TOKEN

ENTRYPOINT ["python", "-m", "src"]

FROM otel/opentelemetry-collector-contrib:0.101.0
COPY otel-collector-config.yaml otel-collector-config.yaml
# Inject environment variables before running the service
CMD ["sh", "-c", "envsubst < /etc/otel-collector-config.yaml > /tmp/otel-collector-config.yaml && exec /otelcol-contrib --config /tmp/otel-collector-config.yaml"]

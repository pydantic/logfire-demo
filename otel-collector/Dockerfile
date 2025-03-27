FROM otel/opentelemetry-collector-contrib:0.114.0

# Copy configuration and entry script
COPY otel-collector-config.yaml /etc/otel-collector-config.yaml

CMD [ "--config=/etc/otel-collector-config.yaml" ]

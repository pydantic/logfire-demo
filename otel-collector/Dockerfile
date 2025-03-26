FROM otel/opentelemetry-collector-contrib:0.101.0

# Install envsubst (part of gettext)
RUN apt-get update && apt-get install -y gettext-base

# Copy configuration and entry script
COPY otel-collector-config.yaml /etc/otel-collector-config.yaml
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh  # Make script executable

# Use the script as the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

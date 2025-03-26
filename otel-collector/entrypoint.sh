#!/bin/sh
set -e  # Exit if any command fails

# Use envsubst to replace environment variables in the config file
envsubst < /etc/otel-collector-config.yaml > /tmp/otel-collector-config.yaml

# Start the OpenTelemetry Collector with the new config
exec /otelcol-contrib --config /tmp/otel-collector-config.yaml

# Standalone SigNoz

This example starts a pinned SigNoz Docker Compose deployment for one developer
machine. It includes SigNoz, ClickHouse, the OpenTelemetry collector, migrations,
and persistent Docker volumes.

```bash
./signoz.sh up
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
../../../../loopctl telemetry-test
```

Open `http://localhost:8080`, complete the local account setup, then filter traces
by `service.name = agentic-loop`.

The helper downloads SigNoz `v0.128.0` on first use, then runs the local
`docker-compose.yml`, which includes the pinned deployment. The supported
standalone stack contains several coordinated Compose and ClickHouse
configuration files.

```bash
./signoz.sh status
./signoz.sh logs
./signoz.sh down
```

SigNoz requires Docker Compose and at least 4 GB of memory. Ports `8080`, `4317`,
and `4318` must be available.

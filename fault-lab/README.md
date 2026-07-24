# KaiOps Fault Lab

This is the application that **causes the monitored symptoms** corresponding to
the 50 KaiOps incident scenarios. It is not a Jira ticket simulator.

The application deliberately produces bounded failures inside its own process:

- HTTP 500, 503, 504 and 401 responses
- controlled response latency
- JSON exception logs and stack traces
- application error-rate signals
- queue/consumer backlog signals
- database and connection-pool signals
- CPU, memory and storage saturation signals
- pipeline, certificate, networking and telemetry signals

Prometheus, Datadog, New Relic, Splunk or KaiOps should ingest the signals and
create/correlate the alerts and tickets.

## Safety

This lab does not actually fill disks, consume unbounded memory, exhaust host
threads, change certificates, disconnect networks or access external systems.
It reproduces the application-visible symptoms and breached metrics in a
bounded, reversible manner.

## Run with Python

Python 3.10+ is required. There are no third-party Python dependencies.

```bash
python fault_lab.py
```

Open:

- Fault dashboard: <http://localhost:8080>
- Prometheus metrics: <http://localhost:8080/metrics>
- Scenario catalogue: <http://localhost:8080/api/scenarios>
- Application logs: `runtime/application.log`

## Start a fault

```bash
curl -X POST "http://localhost:8080/api/faults/kaiops-scenario-01/start?duration=90"
```

Then call the affected application workload:

```bash
curl -i http://localhost:8080/workload/checkout-api
```

During the fault, the request produces a controlled error and `/metrics` shows:

```text
kaiops_fault_ratio{scenario_id="kaiops-scenario-01",...} <value greater than 1>
```

Prometheus fires `KaiOpsApplicationFaultDetected` after 15 seconds.

Recover immediately:

```bash
curl -X POST http://localhost:8080/api/faults/kaiops-scenario-01/stop
```

The fault automatically recovers when its duration expires.

## Generate workload traffic

In a second terminal:

```bash
python traffic_generator.py
```

This continuously calls all service workload endpoints, producing successful
responses for healthy services and controlled failures for active scenarios.

## Start one scenario automatically

```bash
python fault_lab.py --start kaiops-scenario-01 --duration 120
```

## Run with Prometheus

```bash
docker compose up --build
```

Open:

- Fault Lab: <http://localhost:8080>
- Prometheus: <http://localhost:9090>

The provided rule fires whenever a scenario's normalized signal exceeds its
threshold for 15 seconds.

## Flow

```text
Activate fault
    ↓
Fault Lab emits application errors, logs and breached metrics
    ↓
Prometheus/monitoring detects threshold breach
    ↓
KaiOps alert ingestion creates or correlates an incident
    ↓
Historical Jira ticket, RCA and resolution context can be retrieved
```

## Relationship to the 1,000 tickets

The 1,000 tickets contain 20 occurrences of each of the 50 scenarios. Fault Lab
loads the same CSV but extracts one fault definition per scenario. Each metric
and log includes:

- `scenario_id`
- service and component
- severity and alert name
- `ticket_example`, pointing to one representative historical ticket

New executions have a new `fault_id` and trace IDs because they represent fresh
runtime events. KaiOps should create a new ticket or correlate the event with an
existing open incident according to its deduplication policy.

# GPU Monitoring

## Overview

DeepIRI ZepGPU provides comprehensive monitoring for GPU utilization, task metrics, and system health.

## Metrics Collector

```python
from deepiri_zepgpu.monitoring import MetricsCollector

collector = MetricsCollector(collect_interval=5.0)
await collector.start()

# Get summary
summary = collector.get_summary()
print(f"CPU: {summary['system']['cpu_percent_avg']}%")
print(f"GPU Util: {summary['gpu']['utilization_avg']}%")

await collector.stop()
```

## GPU Information

```python
from deepiri_zepgpu.utils.gpu_utils import get_gpu_info, format_memory

info = get_gpu_info()

for gpu in info["gpus"]:
    print(f"GPU {gpu['index']}: {gpu['name']}")
    print(f"  Total Memory: {format_memory(gpu['total_memory'])}")
```

## Structured Logging

```python
from deepiri_zepgpu.monitoring import get_logger

logger = get_logger()
logger.set_context(user_id="researcher1")

logger.info("Task completed", task_id="123", duration_ms=150)
logger.warning("Queue backlog", queue_length=50)
logger.error("Task failed", task_id="123", error="OOM")
```

## Alert System

```python
from deepiri_zepgpu.monitoring import AlertManager, AlertType, AlertSeverity

alerts = AlertManager()
alerts.add_handler(WebhookAlertHandler("https://hooks.example.com/alerts"))

await alerts.alert_task_timeout(task_id, timeout_seconds=3600)
await alerts.alert_gpu_overtemp(device_id=0, temperature=87)
```

## WebSocket Dashboard

```python
from deepiri_zepgpu.monitoring import MonitoringDashboard

dashboard = MonitoringDashboard(port=8765)
await dashboard.start()

# Broadcast updates
await dashboard.broadcast_task_update(task_id, "completed")
await dashboard.broadcast_gpu_metrics({"utilization": 85})

await dashboard.stop()
```

## Prometheus Export

```python
from deepiri_zepgpu.monitoring import PrometheusExporter

prom = PrometheusExporter()

prom.set_gauge("gpu_utilization", 85.0, {"device": "0"})
prom.increment_counter("tasks_completed", 1)
prom.record_histogram("task_duration", 150.0, {"user": "alice"})

# Expose at /metrics endpoint
print(prom.get_metrics())
```

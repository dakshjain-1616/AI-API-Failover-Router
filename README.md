# AI API Failover Router

> Built autonomously by [NEO](https://heyneo.com) — your fully autonomous AI coding agent. &nbsp; [![NEO for VS Code](https://img.shields.io/badge/VS%20Code-NEO%20Extension-5C2D91?logo=visual-studio-code&logoColor=white)](https://marketplace.visualstudio.com/items?itemName=NeoResearchInc.heyneo)

![Architecture](./infographic.svg)

A production-ready HTTP proxy for LLM APIs. Route any OpenAI-compatible request through a configurable chain of providers — Ollama, OpenAI, Anthropic, DeepSeek, or any OpenAI-compatible endpoint — with automatic failover, circuit breakers, and Prometheus metrics.

---

## Why This Exists

AI API outages, rate limits, and cost spikes are unpredictable. Most production apps hardcode a single provider and break when it does. This router solves that:

- **Zero downtime** — when your primary provider fails, traffic automatically shifts to the next healthy one
- **Cost control** — route cheapest-first, or set a per-request cost ceiling
- **One endpoint, any backend** — your app talks to `localhost:8000`, never knowing or caring which model actually answered
- **No vendor lock-in** — swap providers, add new ones, or run fully local (Ollama) without changing your app

---

## What It Does

```
Your App  ──►  localhost:8000/v1/chat/completions
                        │
                   Router decides:
                   ┌────────────────────────────────┐
                   │  Strategy: PRIORITY / COST /   │
                   │           LATENCY / HEALTH     │
                   └────────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      Ollama        DeepSeek       OpenAI
      (local)       (cheap)     (fallback)
          │             │             │
    Circuit         Circuit       Circuit
    Breaker         Breaker       Breaker
    (CLOSED)        (CLOSED)      (OPEN → skip)
```

When a provider fails 3 times, its circuit breaker opens. The router skips it automatically, tries the next provider in the chain, and re-probes the failed one every 30 seconds. Recovery is fully automatic.

---

## Why It Matters

| Without this router | With this router |
|--------------------|-----------------|
| App breaks when OpenAI has an outage | Automatic failover to Anthropic or local Ollama |
| Pay OpenAI rates for every request | Route to free Ollama first, pay APIs only when needed |
| No visibility into costs or latency | Per-provider Prometheus metrics, p50/p95/p99 latency |
| Changing providers requires code changes | Change `config.yaml`, zero code changes |

---

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure `config.yaml`

Add your provider API keys. Only the providers you configure are used:

```yaml
providers:
  ollama:
    name: "ollama"
    type: "ollama"
    base_url: "http://localhost:11434"
    model: "llama3"
    cost_per_token: 0.0
    priority: 1
    enabled: true

  openai:
    name: "openai"
    type: "openai"
    base_url: "https://api.openai.com/v1"
    api_key: "sk-your-openai-key"
    model: "gpt-5.4-mini"
    cost_per_token: 0.0000025
    priority: 2
    enabled: true

  anthropic:
    name: "anthropic"
    type: "anthropic"
    base_url: "https://api.anthropic.com/v1"
    api_key: "sk-ant-your-anthropic-key"
    model: "claude-haiku-4-5-20251001"
    cost_per_token: 0.000001
    priority: 3
    enabled: true

  deepseek:
    name: "deepseek"
    type: "deepseek"
    base_url: "https://api.deepseek.com/v1"
    api_key: "sk-your-deepseek-key"
    model: "deepseek-chat"
    cost_per_token: 0.00000014
    priority: 4
    enabled: true

routing:
  strategy: "priority"           # priority | cost | latency | health
  fallback_chain: ["ollama", "openai", "anthropic", "deepseek"]
  cost_threshold: 1.0            # max USD per request
  latency_threshold: 5.0         # max seconds

health_check:
  interval: 60.0                 # seconds between checks
  failure_threshold: 3           # failures before circuit opens
  recovery_timeout: 30.0         # seconds before retry

server:
  host: "0.0.0.0"
  port: 8000
```

### 3. Run the server

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 4. Run tests

```bash
python3 -m pytest tests/ -v
```

```
tests/test_config.py::TestProviderConfig::test_provider_config_minimal PASSED
tests/test_config.py::TestProviderConfig::test_provider_config_validation PASSED
tests/test_health.py::TestCircuitBreaker::test_initial_state_closed PASSED
tests/test_health.py::TestCircuitBreaker::test_closed_to_open_on_failure_threshold PASSED
tests/test_router.py::TestFailoverLogic::test_primary_success_no_failover PASSED
tests/test_router.py::TestFailoverLogic::test_router_handles_timeout PASSED
...
============================== 55 passed in 0.95s ==============================
```

---

## Usage Examples

### Chat Completion (OpenAI-compatible)

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "model": "gpt-5.4-mini",
    "temperature": 0.7
  }'
```

**Response** (with a real provider configured):

```json
{
    "id": "chatcmpl-1744123456",
    "object": "chat.completion",
    "created": 1744123456,
    "model": "gpt-5.4-mini",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! I'm doing well, thank you for asking. How can I help you today?"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "input_tokens": 13,
        "output_tokens": 17,
        "total_tokens": 30
    },
    "x_provider": "openai"
}
```

> `x_provider` tells you which backend actually served the request.

### Text Completion (Legacy)

```bash
curl -X POST http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "The capital of France is",
    "model": "gpt-5.4-mini",
    "max_tokens": 10
  }'
```

**Response:**

```json
{
    "id": "cmpl-1744123456",
    "object": "text_completion",
    "created": 1744123456,
    "model": "gpt-5.4-mini",
    "choices": [
        {
            "text": " Paris.",
            "index": 0,
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10
    }
}
```

### Python SDK — drop-in replacement

```python
from openai import OpenAI

# Point the client at the router instead of OpenAI directly
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"           # router handles auth per-provider
)

response = client.chat.completions.create(
    model="gpt-5.4-mini",
    messages=[{"role": "user", "content": "Explain circuit breakers in one sentence."}]
)

print(response.choices[0].message.content)
# The serving provider is in response.model or x_provider header
```

### Auth (if enabled)

```bash
# Bearer token
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-router-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hi"}]}'

# X-API-Key header
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: your-router-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hi"}]}'
```

---

## API Reference

All responses use JSON. All endpoints return appropriate HTTP status codes.

### `GET /health`

Per-provider health and circuit breaker state.

```bash
curl http://localhost:8000/health
```

```json
{
    "status": "healthy",
    "providers": {
        "ollama": {
            "state": "closed",
            "healthy": true,
            "failure_count": 1,
            "success_count": 0,
            "consecutive_failures": 1,
            "consecutive_successes": 0,
            "last_failure_time": 1775798944.056,
            "last_success_time": 0.0,
            "provider_type": "ollama",
            "provider_enabled": true
        },
        "openai": {
            "state": "closed",
            "healthy": true,
            "failure_count": 1,
            "success_count": 0,
            "consecutive_failures": 1,
            "consecutive_successes": 0,
            "last_failure_time": 1775798944.327,
            "last_success_time": 0.0,
            "provider_type": "openai",
            "provider_enabled": true
        },
        "anthropic": {
            "state": "closed",
            "healthy": true,
            "failure_count": 1,
            "success_count": 0,
            "consecutive_failures": 1,
            "consecutive_successes": 0,
            "last_failure_time": 1775798944.543,
            "last_success_time": 0.0,
            "provider_type": "anthropic",
            "provider_enabled": true
        },
        "deepseek": {
            "state": "closed",
            "healthy": true,
            "failure_count": 1,
            "success_count": 0,
            "consecutive_failures": 1,
            "consecutive_successes": 0,
            "last_failure_time": 1775798944.869,
            "last_success_time": 0.0,
            "provider_type": "deepseek",
            "provider_enabled": true
        }
    },
    "healthy_count": 4,
    "unhealthy_count": 0,
    "last_check": 1775799002.945
}
```

`state` values: `closed` (normal), `open` (blocked), `half_open` (recovering).

---

### `GET /stats`

Aggregated request statistics per provider.

```bash
curl http://localhost:8000/stats
```

```json
{
    "total_requests": 4,
    "total_failovers": 4,
    "providers": {
        "ollama": {
            "provider": "ollama",
            "total_requests": 1,
            "latency": {
                "mean": 124.5,
                "p50": 120.1,
                "p95": 198.3,
                "p99": 210.0,
                "min": 98.2,
                "max": 210.0,
                "count": 1
            },
            "tokens": {"input": 13, "output": 17, "total": 30},
            "cost_usd": 0.0,
            "failures": 0,
            "failovers": 0,
            "success_rate": 1.0
        },
        "openai": {
            "provider": "openai",
            "total_requests": 3,
            "latency": {
                "mean": 312.7,
                "p50": 305.2,
                "p95": 420.1,
                "p99": 445.3,
                "min": 280.1,
                "max": 445.3,
                "count": 3
            },
            "tokens": {"input": 45, "output": 62, "total": 107},
            "cost_usd": 0.000107,
            "failures": 1,
            "failovers": 1,
            "success_rate": 0.667
        }
    }
}
```

---

### `GET /metrics`

Prometheus exposition format. Scrape with Prometheus or any compatible tool.

```bash
curl http://localhost:8000/metrics
```

```
# AI API Failover Router Metrics
# Generated at: 1775799030.926

# HELP router_total_requests Total number of requests
# TYPE router_total_requests counter
router_total_requests 4

# HELP router_total_failovers Total number of failover events
# TYPE router_total_failovers counter
router_total_failovers 4

# HELP router_provider_requests Requests per provider
# TYPE router_provider_requests counter
router_provider_requests{provider="ollama"} 1

# HELP router_latency_p50 Latency 50th percentile in ms
# TYPE router_latency_p50 gauge
router_latency_p50{provider="ollama"} 120.100

# HELP router_latency_p95 Latency 95th percentile in ms
# TYPE router_latency_p95 gauge
router_latency_p95{provider="ollama"} 198.300

# HELP router_latency_p99 Latency 99th percentile in ms
# TYPE router_latency_p99 gauge
router_latency_p99{provider="ollama"} 210.000

# HELP router_tokens_total Total tokens processed
# TYPE router_tokens_total counter
router_tokens_total{provider="ollama"} 30

# HELP router_cost_total Total cost in USD
# TYPE router_cost_total counter
router_cost_total{provider="ollama"} 0.000000

# HELP router_failures_total Total failures
# TYPE router_failures_total counter
router_failures_total{provider="ollama"} 0

router_provider_requests{provider="openai"} 3
router_latency_p50{provider="openai"} 305.200
router_latency_p95{provider="openai"} 420.100
router_latency_p99{provider="openai"} 445.300
router_tokens_total{provider="openai"} 107
router_cost_total{provider="openai"} 0.000107
router_failures_total{provider="openai"} 1
```

---

### `GET /admin/providers`

List all configured providers and the active fallback chain.

```bash
curl http://localhost:8000/admin/providers
```

```json
{
    "providers": [
        "ollama",
        "openai",
        "anthropic",
        "deepseek",
        "generic"
    ],
    "fallback_chain": [
        "ollama",
        "openai",
        "anthropic",
        "deepseek",
        "generic"
    ],
    "strategy": "priority"
}
```

---

### `GET /admin/strategy`

Current routing strategy with live provider ordering.

```bash
curl http://localhost:8000/admin/strategy
```

```json
{
    "strategy": "priority",
    "fallback_chain": [
        "ollama",
        "openai",
        "anthropic",
        "deepseek",
        "generic"
    ],
    "cost_threshold": 1.0,
    "latency_threshold": 5.0,
    "available_providers": [
        "ollama",
        "openai",
        "anthropic",
        "deepseek"
    ],
    "ordered_providers": [
        "ollama",
        "openai",
        "anthropic",
        "deepseek"
    ]
}
```

`available_providers` are those with a CLOSED or HALF_OPEN circuit. `generic` is excluded because it is disabled in `config.yaml`.

---

### `GET /admin/circuit/{provider}`

Circuit breaker state for a specific provider.

```bash
curl http://localhost:8000/admin/circuit/openai
```

```json
{
    "provider": "openai",
    "state": "closed",
    "failure_count": 2,
    "can_execute": true
}
```

```bash
# Provider not found
curl http://localhost:8000/admin/circuit/nonexistent
```

```json
{"detail": "Provider 'nonexistent' not found"}
```

HTTP 404.

---

### `POST /admin/circuit/{provider}/reset`

Manually close a circuit breaker — useful after fixing a provider issue.

```bash
curl -X POST http://localhost:8000/admin/circuit/ollama/reset
```

```json
{
    "provider": "ollama",
    "state": "closed",
    "message": "Circuit breaker reset"
}
```

---

### `GET /admin/metrics/{provider}`

Per-provider request metrics with latency percentiles.

```bash
curl http://localhost:8000/admin/metrics/openai
```

```json
{
    "provider": "openai",
    "total_requests": 3,
    "latency": {
        "mean": 312.7,
        "p50": 305.2,
        "p95": 420.1,
        "p99": 445.3,
        "min": 280.1,
        "max": 445.3,
        "count": 3
    },
    "tokens": {
        "input": 45,
        "output": 62,
        "total": 107
    },
    "cost_usd": 0.000107,
    "failures": 1,
    "failovers": 1,
    "success_rate": 0.667
}
```

---

### Error Responses

```bash
# Missing messages field → 400
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-5.4"}'
```
```json
{"detail": "Messages required"}
```
HTTP 400.

```bash
# All providers failed / unavailable → 503
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hi"}]}'
```
```json
{"detail": "[router] All 4 providers failed"}
```
HTTP 503.

```bash
# Missing prompt in /v1/completions → 400
curl -X POST http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-5.4"}'
```
```json
{"detail": "Prompt required"}
```
HTTP 400.

---

## Routing Strategies

Set `routing.strategy` in `config.yaml`:

| Strategy | Behaviour |
|----------|-----------|
| `priority` | Always try providers in configured `fallback_chain` order |
| `cost` | Route to cheapest healthy provider (`cost_per_token` × estimated tokens) |
| `latency` | Route to provider with lowest p50 latency from recent history |
| `health` | Route to provider with best circuit state (CLOSED > HALF_OPEN > OPEN) |

---

## Circuit Breaker

```
CLOSED ──(3 failures)──► OPEN ──(30s timeout)──► HALF_OPEN ──(2 successes)──► CLOSED
  │                        │                          │
Normal                  Skipped                  1 test request
operation               by router                 allowed through
                                                       │
                                               (any failure) ──► OPEN
```

All thresholds are configurable in `config.yaml` under `health_check`.

---

## Middleware

| Layer | What it does |
|-------|-------------|
| Request logging | Logs every request: `METHOD PATH → STATUS (Xms)` |
| Auth validation | Optional Bearer token / X-API-Key validation |
| Rate limiting | Per-client limits (100 req/min by default) |
| Idempotency | Cache responses by `X-Idempotency-Key` header (1h TTL) |

---

## Supported Providers

| Provider | Type | Auth | Default model |
|----------|------|------|---------------|
| Ollama | Local inference | None required | `llama3` |
| OpenAI | GPT-5.4, GPT-5.4-mini, GPT-5.4-nano | `api_key` in config | `gpt-5.4-mini` |
| Anthropic | Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 | `api_key` in config | `claude-haiku-4-5-20251001` |
| DeepSeek | DeepSeek-V3.2 (chat + reasoner) | `api_key` in config | `deepseek-chat` |
| Generic | Any OpenAI-compatible API | Optional `api_key` | configurable |

---

## Project Structure

```
ai-api-failover-router/
├── src/
│   ├── main.py          # FastAPI app + all endpoint handlers
│   ├── router.py        # Failover logic + 4 routing strategies
│   ├── health.py        # Circuit breaker (3-state) + background health checker
│   ├── metrics.py       # Rolling-window latency stats + Prometheus export
│   ├── middleware.py    # Logging, auth, rate limiting, idempotency
│   ├── config.py        # YAML loader + Pydantic validation models
│   └── providers/
│       ├── base.py      # Abstract BaseProvider interface
│       ├── ollama.py    # Ollama (local inference)
│       ├── openai.py    # OpenAI API
│       ├── anthropic.py # Anthropic API (Claude)
│       ├── deepseek.py  # DeepSeek API
│       └── generic.py   # Any OpenAI-compatible endpoint
├── tests/
│   ├── conftest.py
│   ├── test_config.py   # 10 tests
│   ├── test_health.py   # 12 tests
│   ├── test_metrics.py  # 10 tests
│   ├── test_providers.py # 10 tests
│   └── test_router.py   # 13 tests
├── config.yaml
├── requirements.txt
└── pytest.ini
```

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

55 tests across 5 modules — config loading, circuit breaker state transitions, metrics rolling windows, all provider implementations, and router failover logic. No running server required.

```
tests/test_config.py::TestProviderConfig::test_provider_config_minimal PASSED
tests/test_health.py::TestCircuitBreaker::test_closed_to_open_on_failure_threshold PASSED
tests/test_health.py::TestCircuitBreaker::test_open_to_half_open_after_recovery_timeout PASSED
tests/test_metrics.py::TestMetricsCollector::test_failure_tracking PASSED
tests/test_router.py::TestFailoverLogic::test_router_handles_timeout PASSED
...
============================== 55 passed in 0.95s ==============================
```

---

## License

MIT

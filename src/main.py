"""
FastAPI application for AI API Failover Router.
Provides endpoints for chat completions, health, metrics, and admin operations.
"""

import asyncio
import os
import time
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import get_config, AppConfig
from .providers.base import ProviderResponse, ProviderError
from .providers import (
    OllamaProvider, OpenAIProvider, AnthropicProvider,
    DeepSeekProvider, GenericProvider
)
from .router import Router, RoutingStrategy
from .health import CircuitBreaker, HealthChecker, CircuitState, get_health_report
from .metrics import MetricsCollector
from .middleware import create_middleware_stack


# Global instances
config: Optional[AppConfig] = None
router: Optional[Router] = None
health_checker: Optional[HealthChecker] = None
metrics: Optional[MetricsCollector] = None
circuit_breaker: Optional[CircuitBreaker] = None


def create_app(config_path: str = "config.yaml") -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Args:
        config_path: Path to configuration YAML file
    
    Returns:
        Configured FastAPI application
    """
    global config, router, health_checker, metrics, circuit_breaker
    
    # Load configuration
    config = get_config(config_path)
    
    # Create FastAPI app
    app = FastAPI(
        title="AI API Failover Router",
        description="Production-quality LLM API router with automatic failover",
        version="1.0.0"
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Create providers
    providers: Dict[str, Any] = {}
    
    for name, provider_config in config.providers.items():
        provider_type = provider_config.type
        
        if provider_type == "ollama":
            providers[name] = OllamaProvider(provider_config.model_dump())
        elif provider_type == "openai":
            providers[name] = OpenAIProvider(provider_config.model_dump())
        elif provider_type == "anthropic":
            providers[name] = AnthropicProvider(provider_config.model_dump())
        elif provider_type == "deepseek":
            providers[name] = DeepSeekProvider(provider_config.model_dump())
        elif provider_type == "generic":
            providers[name] = GenericProvider(provider_config.model_dump())
        else:
            print(f"Warning: Unknown provider type '{provider_type}' for '{name}'")
    
    # Create circuit breaker
    circuit_breaker = CircuitBreaker(
        failure_threshold=config.health_check.failure_threshold,
        recovery_timeout=config.health_check.recovery_timeout,
        success_threshold=config.health_check.success_threshold
    )
    
    # Create metrics collector
    metrics = MetricsCollector(
        window_size=config.metrics.rolling_window_size
    )
    
    # Create router
    routing_strategy = RoutingStrategy(config.routing.strategy)
    
    router = Router(
        providers=providers,
        circuit_breaker=circuit_breaker,
        metrics=metrics,
        strategy=routing_strategy,
        fallback_chain=config.routing.fallback_chain,
        cost_threshold=config.routing.cost_threshold,
        latency_threshold=config.routing.latency_threshold,
        default_timeout=config.routing.default_timeout
    )
    
    # Create health checker
    health_checker = HealthChecker(
        circuit_breaker=circuit_breaker,
        check_interval=config.health_check.interval,
        check_timeout=config.health_check.timeout
    )
    
    # Register enabled providers with health checker
    for name, provider in providers.items():
        if provider.enabled:
            health_checker.register_provider(name, provider)
    
    # Apply middleware using FastAPI's built-in support
    # Request logging
    from .middleware import RequestLoggingMiddleware
    app.add_middleware(RequestLoggingMiddleware)
    
    # Auth validation
    from .middleware import AuthValidationMiddleware
    app.add_middleware(AuthValidationMiddleware, api_key=config.server.api_key)
    
    # Rate limiting
    from .middleware import RateLimitMiddleware
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=config.server.rate_limit_requests,
        requests_per_hour=config.server.rate_limit_requests * 10
    )
    
    # Idempotency
    from .middleware import IdempotencyMiddleware
    app.add_middleware(IdempotencyMiddleware, cache_ttl_seconds=3600)
    
    # Register endpoints
    register_endpoints(app)
    
    # Start background health checker
    @asynccontextmanager
    async def lifespan(app):
        # Start health checker on startup
        await health_checker.start_background_checker()
        yield
        # Cleanup on shutdown
        await health_checker.stop_background_checker()
    
    app.router.lifespan_context = lifespan
    
    return app


def register_endpoints(app: FastAPI):
    """Register all API endpoints."""
    
    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        x_api_key: Optional[str] = Header(None),
        x_idempotency_key: Optional[str] = Header(None)
    ):
        """
        Chat completions endpoint (OpenAI-compatible).
        
        Routes request to appropriate provider based on routing strategy
        with automatic failover to backup providers.
        """
        try:
            # Parse request body
            body = await request.json()
            messages = body.get("messages", [])

            if not messages:
                raise HTTPException(status_code=400, detail="Messages required")

            # Resolve params: body values take precedence over query-param defaults
            _model = model or body.get("model")
            _temperature = body.get("temperature", temperature)
            _max_tokens = body.get("max_tokens", max_tokens)
            _stream = body.get("stream", stream)

            # Exclude already-handled keys from extra kwargs
            _skip = {"messages", "model", "temperature", "max_tokens", "stream"}
            _extra = {k: v for k, v in body.items() if k not in _skip}

            # Execute with failover
            response, provider_name = await router.execute_with_failover(
                messages=messages,
                model=_model,
                temperature=_temperature,
                max_tokens=_max_tokens,
                stream=_stream,
                **_extra
            )

            # Format response
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": response.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response.content
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": response.usage,
                "x_provider": provider_name
            }

        except HTTPException:
            raise
        except ProviderError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/v1/completions")
    async def completions(
        request: Request,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ):
        """
        Completions endpoint (OpenAI-compatible).
        
        Similar to chat/completions but for text completion tasks.
        """
        try:
            body = await request.json()
            prompt = body.get("prompt", "")

            if not prompt:
                raise HTTPException(status_code=400, detail="Prompt required")

            # Convert prompt to message format
            messages = [{"role": "user", "content": prompt}]

            # Resolve params: body values take precedence over query-param defaults
            _model = model or body.get("model")
            _temperature = body.get("temperature", temperature)
            _max_tokens = body.get("max_tokens", max_tokens)
            _stream = body.get("stream", stream)

            response, provider_name = await router.execute_with_failover(
                messages=messages,
                model=_model,
                temperature=_temperature,
                max_tokens=_max_tokens,
                stream=_stream
            )

            return {
                "id": f"cmpl-{int(time.time())}",
                "object": "text_completion",
                "created": int(time.time()),
                "model": response.model,
                "choices": [
                    {
                        "text": response.content,
                        "index": 0,
                        "finish_reason": "stop"
                    }
                ],
                "usage": response.usage
            }

        except HTTPException:
            raise
        except ProviderError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/health")
    async def health():
        """
        Health check endpoint.

        Returns current health status of all providers.
        """
        report = get_health_report(circuit_breaker, health_checker)
        healthy_count = sum(1 for p in report.providers.values() if p["healthy"])
        unhealthy_count = len(report.providers) - healthy_count

        return {
            "status": "healthy" if healthy_count > 0 else "unhealthy",
            "providers": report.providers,
            "healthy_count": healthy_count,
            "unhealthy_count": unhealthy_count,
            "last_check": report.timestamp
        }
    
    @app.get("/metrics")
    async def metrics_endpoint():
        """
        Prometheus metrics endpoint.

        Returns metrics in Prometheus exposition format.
        """
        return PlainTextResponse(
            metrics.export_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    
    @app.get("/stats")
    async def stats():
        """
        Statistics endpoint.

        Returns aggregated statistics about router performance.
        """
        return metrics.get_all_stats()
    
    @app.get("/admin/providers")
    async def admin_providers():
        """
        Admin endpoint: List all configured providers.
        """
        return {
            "providers": list(router.providers.keys()),
            "fallback_chain": router.fallback_chain,
            "strategy": router.strategy.value
        }
    
    @app.get("/admin/strategy")
    async def admin_strategy():
        """
        Admin endpoint: Get current routing strategy info.
        """
        return router.get_strategy_info()
    
    @app.get("/admin/circuit/{provider_name}")
    async def admin_circuit(provider_name: str):
        """
        Admin endpoint: Get circuit breaker state for a provider.
        """
        if provider_name not in router.providers:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
        
        state = circuit_breaker.get_state(provider_name)
        failures = circuit_breaker.get_or_create_health(provider_name).failure_count
        
        return {
            "provider": provider_name,
            "state": state.value,
            "failure_count": failures,
            "can_execute": circuit_breaker.can_execute(provider_name)
        }
    
    @app.post("/admin/circuit/{provider_name}/reset")
    async def admin_circuit_reset(provider_name: str):
        """
        Admin endpoint: Reset circuit breaker for a provider.
        """
        if provider_name not in router.providers:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
        
        circuit_breaker.reset(provider_name)
        
        return {
            "provider": provider_name,
            "state": circuit_breaker.get_state(provider_name).value,
            "message": "Circuit breaker reset"
        }
    
    @app.get("/admin/metrics/{provider_name}")
    async def admin_metrics(provider_name: str):
        """
        Admin endpoint: Get metrics for a specific provider.
        """
        if provider_name not in router.providers:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
        
        return metrics.get_provider_stats(provider_name)


# Create app instance
_config_path = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.yaml')
)
app = create_app(_config_path)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.server.port if config else 8000,
        log_level="info"
    )

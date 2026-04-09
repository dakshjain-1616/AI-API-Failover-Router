"""
Metrics collection and Prometheus export for AI API Failover Router.
Tracks latency, token usage, cost, and failover events with rolling window statistics.
"""

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import deque
import statistics


@dataclass
class RequestMetric:
    """Single request metric record."""
    provider_name: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost: float
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    failover: bool = False


class RollingWindowStats:
    """
    Rolling window statistics calculator for metrics.
    Maintains a fixed-size window of recent values.
    """
    
    def __init__(self, window_size: int = 1000):
        """
        Initialize rolling window.
        
        Args:
            window_size: Maximum number of values to keep
        """
        self.window_size = window_size
        self.values: deque = deque(maxlen=window_size)
    
    def add(self, value: float):
        """Add a value to the window."""
        self.values.append(value)
    
    def get_stats(self) -> Dict[str, float]:
        """
        Calculate statistics for current window.
        
        Returns:
            Dict with mean, p50, p95, p99, min, max, count
        """
        if not self.values:
            return {
                "mean": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "min": 0.0,
                "max": 0.0,
                "count": 0
            }
        
        sorted_values = sorted(self.values)
        n = len(sorted_values)
        
        return {
            "mean": statistics.mean(sorted_values),
            "p50": sorted_values[int(n * 0.50)] if n > 0 else 0.0,
            "p95": sorted_values[int(n * 0.95)] if n > 0 else 0.0,
            "p99": sorted_values[int(n * 0.99)] if n > 0 else 0.0,
            "min": min(sorted_values),
            "max": max(sorted_values),
            "count": n
        }


class MetricsCollector:
    """
    Collects and aggregates metrics for all providers.
    Provides Prometheus-format export.
    """
    
    def __init__(self, window_size: int = 1000):
        """
        Initialize metrics collector.
        
        Args:
            window_size: Rolling window size for latency stats
        """
        self.window_size = window_size
        self.requests: List[RequestMetric] = []
        self.provider_latency: Dict[str, RollingWindowStats] = {}
        self.provider_tokens: Dict[str, Dict[str, int]] = {}
        self.provider_cost: Dict[str, float] = {}
        self.provider_failures: Dict[str, int] = {}
        self.provider_failovers: Dict[str, int] = {}
        self.total_requests: int = 0
        self.total_failovers: int = 0
    
    def _ensure_provider(self, provider_name: str):
        """Ensure tracking structures exist for provider."""
        if provider_name not in self.provider_latency:
            self.provider_latency[provider_name] = RollingWindowStats(self.window_size)
            self.provider_tokens[provider_name] = {"input": 0, "output": 0, "total": 0}
            self.provider_cost[provider_name] = 0.0
            self.provider_failures[provider_name] = 0
            self.provider_failovers[provider_name] = 0
    
    def record_request(
        self,
        provider_name: str,
        latency_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        success: bool = True,
        failover: bool = False
    ):
        """
        Record a completed request.
        
        Args:
            provider_name: Provider that handled the request
            latency_ms: Request latency in milliseconds
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost: Cost in USD
            success: Whether request succeeded
            failover: Whether this was a failover request
        """
        self._ensure_provider(provider_name)
        
        metric = RequestMetric(
            provider_name=provider_name,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            success=success,
            failover=failover
        )
        
        self.requests.append(metric)
        self.total_requests += 1
        
        # Update rolling window
        self.provider_latency[provider_name].add(latency_ms)
        
        # Update token counts
        self.provider_tokens[provider_name]["input"] += input_tokens
        self.provider_tokens[provider_name]["output"] += output_tokens
        self.provider_tokens[provider_name]["total"] += input_tokens + output_tokens
        
        # Update cost
        self.provider_cost[provider_name] += cost
        
        # Update failure count
        if not success:
            self.provider_failures[provider_name] += 1
        
        # Update failover count
        if failover:
            self.provider_failovers[provider_name] += 1
            self.total_failovers += 1
    
    def get_provider_stats(self, provider_name: str) -> Dict[str, Any]:
        """
        Get statistics for a specific provider.
        
        Args:
            provider_name: Provider name
        
        Returns:
            Dict with all metrics for the provider
        """
        self._ensure_provider(provider_name)
        
        latency_stats = self.provider_latency[provider_name].get_stats()
        
        return {
            "provider": provider_name,
            "total_requests": sum(1 for r in self.requests if r.provider_name == provider_name),
            "latency": latency_stats,
            "tokens": self.provider_tokens[provider_name],
            "cost_usd": self.provider_cost[provider_name],
            "failures": self.provider_failures[provider_name],
            "failovers": self.provider_failovers[provider_name],
            "success_rate": 1.0 - (self.provider_failures[provider_name] / max(1, self.provider_tokens[provider_name]["total"]))
        }
    
    def get_all_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all providers.
        
        Returns:
            Dict with aggregated metrics
        """
        provider_stats = {}
        for provider_name in self.provider_latency:
            provider_stats[provider_name] = self.get_provider_stats(provider_name)
        
        return {
            "total_requests": self.total_requests,
            "total_failovers": self.total_failovers,
            "providers": provider_stats
        }
    
    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Returns:
            Prometheus-format metrics string
        """
        lines = []
        lines.append("# AI API Failover Router Metrics")
        lines.append(f"# Generated at: {time.time()}")
        lines.append("")
        
        # Total requests
        lines.append("# HELP router_total_requests Total number of requests")
        lines.append("# TYPE router_total_requests counter")
        lines.append(f"router_total_requests {self.total_requests}")
        lines.append("")
        
        # Total failovers
        lines.append("# HELP router_total_failovers Total number of failover events")
        lines.append("# TYPE router_total_failovers counter")
        lines.append(f"router_total_failovers {self.total_failovers}")
        lines.append("")
        
        # Per-provider metrics
        for provider_name in self.provider_latency:
            stats = self.get_provider_stats(provider_name)
            latency = stats["latency"]
            tokens = stats["tokens"]
            
            # Request count
            lines.append("# HELP router_provider_requests Requests per provider")
            lines.append("# TYPE router_provider_requests counter")
            lines.append(f'router_provider_requests{{provider="{provider_name}"}} {stats["total_requests"]}')
            
            # Latency p50
            lines.append("# HELP router_latency_p50 Latency 50th percentile in ms")
            lines.append("# TYPE router_latency_p50 gauge")
            lines.append(f'router_latency_p50{{provider="{provider_name}"}} {latency["p50"]:.3f}')
            
            # Latency p95
            lines.append("# HELP router_latency_p95 Latency 95th percentile in ms")
            lines.append("# TYPE router_latency_p95 gauge")
            lines.append(f'router_latency_p95{{provider="{provider_name}"}} {latency["p95"]:.3f}')
            
            # Latency p99
            lines.append("# HELP router_latency_p99 Latency 99th percentile in ms")
            lines.append("# TYPE router_latency_p99 gauge")
            lines.append(f'router_latency_p99{{provider="{provider_name}"}} {latency["p99"]:.3f}')
            
            # Token usage
            lines.append("# HELP router_tokens_total Total tokens processed")
            lines.append("# TYPE router_tokens_total counter")
            lines.append(f'router_tokens_total{{provider="{provider_name}"}} {tokens["total"]}')
            
            # Cost
            lines.append("# HELP router_cost_total Total cost in USD")
            lines.append("# TYPE router_cost_total counter")
            lines.append(f'router_cost_total{{provider="{provider_name}"}} {stats["cost_usd"]:.6f}')
            
            # Failures
            lines.append("# HELP router_failures_total Total failures")
            lines.append("# TYPE router_failures_total counter")
            lines.append(f'router_failures_total{{provider="{provider_name}"}} {stats["failures"]}')
            
            lines.append("")
        
        return "\n".join(lines)

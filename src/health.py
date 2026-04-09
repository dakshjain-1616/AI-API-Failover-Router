"""
Circuit breaker and health monitoring system for AI API Failover Router.
Implements circuit breaker pattern with 3 states: CLOSED, OPEN, HALF_OPEN.
"""

import asyncio
import time
from enum import Enum
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

from .providers.base import BaseProvider, HealthStatus


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests flow through
    OPEN = "open"          # Provider unhealthy, requests blocked
    HALF_OPEN = "half_open" # Testing if provider recovered


@dataclass
class ProviderHealth:
    """Health tracking for a single provider."""
    provider_name: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    last_check_time: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    
    def record_failure(self):
        """Record a failure."""
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        self.consecutive_successes = 0
    
    def record_success(self):
        """Record a success."""
        self.success_count += 1
        self.consecutive_successes += 1
        self.last_success_time = time.time()
        self.consecutive_failures = 0


class CircuitBreaker:
    """
    Circuit breaker implementation for provider health management.
    
    State transitions:
    - CLOSED -> OPEN: When failure_count >= failure_threshold
    - OPEN -> HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN -> CLOSED: When success_count >= success_threshold
    - HALF_OPEN -> OPEN: On any failure
    """
    
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            success_threshold: Number of successes before closing circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.providers: Dict[str, ProviderHealth] = {}
    
    def get_or_create_health(self, provider_name: str) -> ProviderHealth:
        """Get or create health tracking for a provider."""
        if provider_name not in self.providers:
            self.providers[provider_name] = ProviderHealth(provider_name=provider_name)
        return self.providers[provider_name]
    
    def can_execute(self, provider_name: str) -> bool:
        """
        Check if a request can be executed for the provider.
        
        Returns:
            True if circuit is CLOSED or HALF_OPEN, False if OPEN
        """
        health = self.get_or_create_health(provider_name)
        
        if health.state == CircuitState.CLOSED:
            return True
        
        if health.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - health.last_failure_time >= self.recovery_timeout:
                health.state = CircuitState.HALF_OPEN
                return True
            return False
        
        # HALF_OPEN - allow one request to test
        return True
    
    def record_success(self, provider_name: str):
        """Record a successful request."""
        health = self.get_or_create_health(provider_name)
        health.record_success()
        
        if health.state == CircuitState.HALF_OPEN:
            if health.consecutive_successes >= self.success_threshold:
                health.state = CircuitState.CLOSED
                health.failure_count = 0
                health.consecutive_failures = 0
    
    def record_failure(self, provider_name: str):
        """Record a failed request."""
        health = self.get_or_create_health(provider_name)
        health.record_failure()
        
        if health.state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN immediately opens circuit
            health.state = CircuitState.OPEN
        elif health.state == CircuitState.CLOSED:
            if health.consecutive_failures >= self.failure_threshold:
                health.state = CircuitState.OPEN
    
    def get_state(self, provider_name: str) -> CircuitState:
        """Get current circuit state for a provider."""
        health = self.get_or_create_health(provider_name)
        
        # Check for automatic state transition
        if health.state == CircuitState.OPEN:
            if time.time() - health.last_failure_time >= self.recovery_timeout:
                health.state = CircuitState.HALF_OPEN
        
        return health.state
    
    def reset(self, provider_name: str):
        """Reset circuit breaker for a provider."""
        if provider_name in self.providers:
            health = self.providers[provider_name]
            health.state = CircuitState.CLOSED
            health.failure_count = 0
            health.success_count = 0
            health.consecutive_failures = 0
            health.consecutive_successes = 0


class HealthChecker:
    """
    Background health checker for providers.
    Periodically checks provider health and updates circuit breaker.
    """
    
    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        check_interval: float = 60.0,
        check_timeout: float = 10.0
    ):
        """
        Initialize health checker.
        
        Args:
            circuit_breaker: Circuit breaker instance to update
            check_interval: Seconds between health checks
            check_timeout: Timeout for health check requests
        """
        self.circuit_breaker = circuit_breaker
        self.check_interval = check_interval
        self.check_timeout = check_timeout
        self.providers: Dict[str, BaseProvider] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def register_provider(self, name: str, provider: BaseProvider):
        """Register a provider for health checking."""
        self.providers[name] = provider
    
    async def check_provider_health(self, provider_name: str) -> HealthStatus:
        """Check health of a single provider."""
        if provider_name not in self.providers:
            return HealthStatus(healthy=False, error="Provider not registered")
        
        provider = self.providers[provider_name]
        try:
            status = await asyncio.wait_for(
                provider.health_check(),
                timeout=self.check_timeout
            )
            
            # Update circuit breaker
            if status.healthy:
                self.circuit_breaker.record_success(provider_name)
            else:
                self.circuit_breaker.record_failure(provider_name)
            
            return status
        except asyncio.TimeoutError:
            self.circuit_breaker.record_failure(provider_name)
            return HealthStatus(healthy=False, error="Health check timeout")
        except Exception as e:
            self.circuit_breaker.record_failure(provider_name)
            return HealthStatus(healthy=False, error=str(e))
    
    async def check_all_providers(self) -> Dict[str, HealthStatus]:
        """Check health of all registered providers."""
        results = {}
        for name in self.providers:
            results[name] = await self.check_provider_health(name)
        return results
    
    async def start_background_checker(self):
        """Start background health check loop."""
        self._running = True
        
        async def health_check_loop():
            while self._running:
                await self.check_all_providers()
                await asyncio.sleep(self.check_interval)
        
        self._task = asyncio.create_task(health_check_loop())
    
    async def stop_background_checker(self):
        """Stop background health check loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


@dataclass
class HealthReport:
    """Complete health report for all providers."""
    providers: Dict[str, Dict[str, Any]]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "timestamp": self.timestamp,
            "providers": self.providers
        }


def get_health_report(
    circuit_breaker: CircuitBreaker,
    health_checker: HealthChecker
) -> HealthReport:
    """
    Generate a complete health report.
    
    Args:
        circuit_breaker: Circuit breaker instance
        health_checker: Health checker instance
    
    Returns:
        HealthReport with all provider status information
    """
    providers_status = {}
    
    for name, provider in health_checker.providers.items():
        health = circuit_breaker.get_or_create_health(name)
        state = circuit_breaker.get_state(name)
        
        providers_status[name] = {
            "state": state.value,
            "healthy": state == CircuitState.CLOSED,
            "failure_count": health.failure_count,
            "success_count": health.success_count,
            "consecutive_failures": health.consecutive_failures,
            "consecutive_successes": health.consecutive_successes,
            "last_failure_time": health.last_failure_time,
            "last_success_time": health.last_success_time,
            "provider_type": provider.type,
            "provider_enabled": provider.enabled
        }
    
    return HealthReport(providers=providers_status)

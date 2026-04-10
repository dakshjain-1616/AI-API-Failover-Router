"""
Core router for AI API Failover Router.
Implements failover chain logic with strategy selection, timeout handling, and cost-based routing.
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from .providers.base import BaseProvider, ProviderResponse, ProviderError, HealthStatus
from .health import CircuitBreaker, HealthChecker, CircuitState
from .metrics import MetricsCollector


class RoutingStrategy(Enum):
    """Available routing strategies."""
    PRIORITY = "priority"      # Use provider priority order
    COST = "cost"              # Route to cheapest available provider
    LATENCY = "latency"        # Route to fastest available provider
    HEALTH = "health"          # Route to healthiest provider


class Router:
    """
    Core router with failover logic.
    
    Routes requests to providers based on strategy, with automatic failover
    to backup providers when primary fails.
    """
    
    def __init__(
        self,
        providers: Dict[str, BaseProvider],
        circuit_breaker: CircuitBreaker,
        metrics: MetricsCollector,
        strategy: RoutingStrategy = RoutingStrategy.PRIORITY,
        fallback_chain: List[str] = None,
        cost_threshold: float = 1.0,
        latency_threshold: float = 5.0,
        default_timeout: float = 30.0
    ):
        """
        Initialize router.
        
        Args:
            providers: Dict of provider name to BaseProvider instance
            circuit_breaker: Circuit breaker for health tracking
            metrics: Metrics collector for recording requests
            strategy: Routing strategy to use
            fallback_chain: Ordered list of provider names for fallback
            cost_threshold: Maximum acceptable cost per request
            latency_threshold: Maximum acceptable latency in seconds
            default_timeout: Default request timeout
        """
        self.providers = providers
        self.circuit_breaker = circuit_breaker
        self.metrics = metrics
        self.strategy = strategy
        self.fallback_chain = fallback_chain or list(providers.keys())
        self.cost_threshold = cost_threshold
        self.latency_threshold = latency_threshold
        self.default_timeout = default_timeout
        
        # Register providers with circuit breaker
        for name, provider in providers.items():
            # Circuit breaker tracks by name automatically
    
            pass
    
    def _get_ordered_providers(self) -> List[str]:
        """
        Get providers ordered by current strategy.
        
        Returns:
            List of provider names in priority order
        """
        available = []
        
        for name in self.fallback_chain:
            if name not in self.providers:
                continue
            
            provider = self.providers[name]
            
            # Skip disabled providers
            if not provider.enabled:
                continue
            
            # Skip providers with open circuits
            if not self.circuit_breaker.can_execute(name):
                continue
            
            available.append(name)
        
        if not available:
            # Last resort: try all enabled providers even with open circuits
            return [n for n in self.providers if self.providers[n].enabled]
        
        # Sort by strategy
        if self.strategy == RoutingStrategy.PRIORITY:
            # Already in fallback_chain order (priority order)
            return available
        
        elif self.strategy == RoutingStrategy.COST:
            # Sort by cost_per_token
            return sorted(available, key=lambda n: self.providers[n].cost_per_token)
        
        elif self.strategy == RoutingStrategy.LATENCY:
            # Sort by recent latency (from metrics)
            def get_latency(name):
                stats = self.metrics.get_provider_stats(name)
                return stats["latency"]["p50"] if stats["total_requests"] > 0 else float('inf')
            return sorted(available, key=get_latency)
        
        elif self.strategy == RoutingStrategy.HEALTH:
            # Sort by circuit state (CLOSED > HALF_OPEN > OPEN)
            def health_score(name):
                state = self.circuit_breaker.get_state(name)
                if state == CircuitState.CLOSED:
                    return 0
                elif state == CircuitState.HALF_OPEN:
                    return 1
                else:
                    return 2
            return sorted(available, key=health_score)
        
        return available
    
    async def execute_with_failover(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Tuple[ProviderResponse, str]:
        """
        Execute request with automatic failover.
        
        Args:
            messages: List of message dicts
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            stream: Whether to stream
            timeout: Request timeout
            **kwargs: Additional parameters
        
        Returns:
            Tuple of (ProviderResponse, provider_name)
        
        Raises:
            ProviderError: If all providers fail
        """
        timeout = timeout or self.default_timeout
        ordered = self._get_ordered_providers()
        
        if not ordered:
            raise ProviderError("No available providers", "router")
        
        for provider_name in ordered:
            provider = self.providers[provider_name]

            # Skip disabled providers
            if not provider.enabled:
                continue

            # Check if we can execute
            if not self.circuit_breaker.can_execute(provider_name):
                continue

            try:
                # Execute with timeout
                start_time = time.time()

                response = await asyncio.wait_for(
                    provider.complete(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=stream,
                        **kwargs
                    ),
                    timeout=timeout
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                # Record success
                self.circuit_breaker.record_success(provider_name)
                self.metrics.record_request(
                    provider_name=provider_name,
                    latency_ms=latency_ms,
                    input_tokens=response.usage.get("input_tokens", 0),
                    output_tokens=response.usage.get("output_tokens", 0),
                    cost=response.cost,
                    success=True
                )
                
                return response, provider_name
            
            except asyncio.TimeoutError as e:
                # Record timeout as failure
                self.circuit_breaker.record_failure(provider_name)
                self.metrics.record_request(
                    provider_name=provider_name,
                    latency_ms=timeout * 1000,
                    success=False,
                    failover=True
                )
                continue
            
            except ProviderError as e:
                # Record provider error
                self.circuit_breaker.record_failure(provider_name)
                self.metrics.record_request(
                    provider_name=provider_name,
                    latency_ms=0.0,
                    success=False,
                    failover=True
                )
                continue
            
            except Exception as e:
                # Record unexpected error
                self.circuit_breaker.record_failure(provider_name)
                self.metrics.record_request(
                    provider_name=provider_name,
                    latency_ms=0.0,
                    success=False,
                    failover=True
                )
                continue
        
        # All providers failed
        raise ProviderError(
            f"All {len(ordered)} providers failed",
            "router"
        )
    
    async def execute_single(
        self,
        provider_name: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        timeout: Optional[float] = None,
        **kwargs
    ) -> ProviderResponse:
        """
        Execute request on a specific provider (no failover).
        
        Args:
            provider_name: Specific provider to use
            messages: List of message dicts
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            stream: Whether to stream
            timeout: Request timeout
            **kwargs: Additional parameters
        
        Returns:
            ProviderResponse
        
        Raises:
            ProviderError: If request fails
        """
        if provider_name not in self.providers:
            raise ProviderError(f"Unknown provider: {provider_name}", "router")
        
        provider = self.providers[provider_name]
        timeout = timeout or self.default_timeout
        
        start_time = time.time()
        
        try:
            response = await asyncio.wait_for(
                provider.complete(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream,
                    **kwargs
                ),
                timeout=timeout
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            self.circuit_breaker.record_success(provider_name)
            self.metrics.record_request(
                provider_name=provider_name,
                latency_ms=latency_ms,
                input_tokens=response.usage.get("input_tokens", 0),
                output_tokens=response.usage.get("output_tokens", 0),
                cost=response.cost,
                success=True
            )
            
            return response
        
        except asyncio.TimeoutError:
            self.circuit_breaker.record_failure(provider_name)
            self.metrics.record_request(
                provider_name=provider_name,
                latency_ms=timeout * 1000,
                success=False
            )
            raise ProviderError(f"Request timeout after {timeout}s", provider_name)
        
        except ProviderError:
            self.circuit_breaker.record_failure(provider_name)
            self.metrics.record_request(
                provider_name=provider_name,
                latency_ms=0.0,
                success=False
            )
            raise
        
        except Exception as e:
            self.circuit_breaker.record_failure(provider_name)
            self.metrics.record_request(
                provider_name=provider_name,
                latency_ms=0.0,
                success=False
            )
            raise ProviderError(str(e), provider_name)
    
    def get_available_providers(self) -> List[str]:
        """
        Get list of currently available providers.
        
        Returns:
            List of provider names that can accept requests
        """
        available = []
        for name in self.providers:
            if self.providers[name].enabled and self.circuit_breaker.can_execute(name):
                available.append(name)
        return available
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """
        Get information about current routing strategy.
        
        Returns:
            Dict with strategy details
        """
        return {
            "strategy": self.strategy.value,
            "fallback_chain": self.fallback_chain,
            "cost_threshold": self.cost_threshold,
            "latency_threshold": self.latency_threshold,
            "available_providers": self.get_available_providers(),
            "ordered_providers": self._get_ordered_providers()
        }

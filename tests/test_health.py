"""
Test circuit breaker and health check system for AI API Failover Router.
"""

import asyncio
import pytest
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.health import CircuitBreaker, HealthChecker, ProviderHealth, CircuitState
from src.providers.base import HealthStatus, BaseProvider


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        health = cb.get_or_create_health("test")
        assert health.state == CircuitState.CLOSED
    
    def test_closed_to_open_on_failure_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        health = cb.get_or_create_health("test")
        for _ in range(3):
            cb.record_failure("test")
        assert health.state == CircuitState.OPEN
    
    def test_open_to_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
        health = cb.get_or_create_health("test")
        for _ in range(3):
            cb.record_failure("test")
        assert health.state == CircuitState.OPEN
        # Wait for recovery timeout
        time.sleep(0.15)
        state = cb.get_state("test")
        assert state == CircuitState.HALF_OPEN
    
    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1, success_threshold=2)
        health = cb.get_or_create_health("test")
        for _ in range(3):
            cb.record_failure("test")
        time.sleep(0.15)
        cb.get_state("test")  # Trigger transition to HALF_OPEN
        assert health.state == CircuitState.HALF_OPEN
        for _ in range(2):
            cb.record_success("test")
        assert health.state == CircuitState.CLOSED
    
    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
        health = cb.get_or_create_health("test")
        for _ in range(3):
            cb.record_failure("test")
        time.sleep(0.15)
        cb.get_state("test")  # Trigger transition to HALF_OPEN
        assert health.state == CircuitState.HALF_OPEN
        cb.record_failure("test")
        assert health.state == CircuitState.OPEN
    
    def test_can_execute_closed(self):
        cb = CircuitBreaker()
        assert cb.can_execute("test") is True
    
    def test_can_execute_open(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure("test")
        assert cb.can_execute("test") is False
    
    def test_can_execute_half_open(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
        for _ in range(3):
            cb.record_failure("test")
        time.sleep(0.15)
        assert cb.can_execute("test") is True  # Half-open allows one test request
    
    def test_reset_circuit(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure("test")
        health = cb.get_or_create_health("test")
        assert health.state == CircuitState.OPEN
        cb.reset("test")
        assert health.state == CircuitState.CLOSED
        assert health.failure_count == 0


class TestHealthChecker:
    def test_register_provider(self):
        cb = CircuitBreaker()
        hc = HealthChecker(circuit_breaker=cb)
        # Create a mock provider
        class MockProvider(BaseProvider):
            async def complete(self, messages, model=None, **kwargs): pass
            async def health_check(self): return HealthStatus(healthy=True)
            async def estimate_cost(self, messages, max_tokens=None): return 0.0
            def normalize_response(self, raw_response, latency_ms): pass
        
        mock = MockProvider({"name": "ollama", "type": "ollama", "base_url": "http://localhost:11434"})
        hc.register_provider("ollama", mock)
        assert "ollama" in hc.providers
    
    def test_check_provider_health(self):
        cb = CircuitBreaker()
        hc = HealthChecker(circuit_breaker=cb)
        
        class MockProvider(BaseProvider):
            async def complete(self, messages, model=None, **kwargs): pass
            async def health_check(self): return HealthStatus(healthy=True, latency_ms=50)
            async def estimate_cost(self, messages, max_tokens=None): return 0.0
            def normalize_response(self, raw_response, latency_ms): pass
        
        mock = MockProvider({"name": "test", "type": "test", "base_url": "http://test"})
        hc.register_provider("test", mock)
        
        async def run_test():
            status = await hc.check_provider_health("test")
            assert status.healthy is True
        
        asyncio.run(run_test())
    
    def test_check_all_providers(self):
        cb = CircuitBreaker()
        hc = HealthChecker(circuit_breaker=cb)
        
        class MockProvider(BaseProvider):
            async def complete(self, messages, model=None, **kwargs): pass
            async def health_check(self): return HealthStatus(healthy=True)
            async def estimate_cost(self, messages, max_tokens=None): return 0.0
            def normalize_response(self, raw_response, latency_ms): pass
        
        mock1 = MockProvider({"name": "p1", "type": "test", "base_url": "http://p1"})
        mock2 = MockProvider({"name": "p2", "type": "test", "base_url": "http://p2"})
        hc.register_provider("p1", mock1)
        hc.register_provider("p2", mock2)
        
        async def run_test():
            results = await hc.check_all_providers()
            assert len(results) == 2
            assert results["p1"].healthy is True
            assert results["p2"].healthy is True
        
        asyncio.run(run_test())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Test metrics collection and Prometheus export for AI API Failover Router.
"""

import pytest
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.metrics import MetricsCollector, RollingWindowStats


class TestRollingWindowStats:
    def test_initial_empty_stats(self):
        stats = RollingWindowStats(window_size=100)
        result = stats.get_stats()
        assert result["count"] == 0
        assert result["p50"] == 0.0
        assert result["p95"] == 0.0
        assert result["p99"] == 0.0
    
    def test_add_values(self):
        stats = RollingWindowStats(window_size=100)
        for i in range(10):
            stats.add(float(i))
        result = stats.get_stats()
        assert result["count"] == 10
        assert result["min"] == 0.0
        assert result["max"] == 9.0
    
    def test_percentile_calculation(self):
        stats = RollingWindowStats(window_size=100)
        # Add 100 values from 0 to 99 (so p50 at index 50 = value 50.0)
        for i in range(100):
            stats.add(float(i))
        result = stats.get_stats()
        assert result["count"] == 100
        assert result["p50"] == 50.0  # 50th percentile (index 50 in 0-99 range)
        assert result["p95"] == 95.0  # 95th percentile
        assert result["p99"] == 99.0  # 99th percentile
    
    def test_window_size_limit(self):
        stats = RollingWindowStats(window_size=10)
        for i in range(100):
            stats.add(float(i))
        result = stats.get_stats()
        assert result["count"] == 10  # Only last 10 values kept
        assert result["min"] == 90.0
        assert result["max"] == 99.0


class TestMetricsCollector:
    def test_record_request(self):
        mc = MetricsCollector(window_size=100)
        mc.record_request(
            provider_name="test",
            latency_ms=150.0,
            input_tokens=100,
            output_tokens=50,
            cost=0.005,
            success=True
        )
        stats = mc.get_provider_stats("test")
        assert stats["total_requests"] == 1
        assert stats["tokens"]["input"] == 100
        assert stats["tokens"]["output"] == 50
        assert stats["cost_usd"] == 0.005
    
    def test_multiple_requests(self):
        mc = MetricsCollector(window_size=100)
        for i in range(5):
            mc.record_request(
                provider_name="test",
                latency_ms=100.0 + i * 10,
                input_tokens=100,
                output_tokens=50,
                cost=0.005,
                success=True
            )
        stats = mc.get_provider_stats("test")
        assert stats["total_requests"] == 5
        assert stats["latency"]["count"] == 5
    
    def test_failure_tracking(self):
        mc = MetricsCollector(window_size=100)
        mc.record_request("test", 100.0, 100, 50, 0.005, success=True)
        mc.record_request("test", 100.0, 100, 50, 0.005, success=False)
        stats = mc.get_provider_stats("test")
        assert stats["failures"] == 1
        assert stats["total_requests"] == 2
    
    def test_failover_tracking(self):
        mc = MetricsCollector(window_size=100)
        mc.record_request("test", 100.0, 100, 50, 0.005, success=True, failover=True)
        stats = mc.get_provider_stats("test")
        assert stats["failovers"] == 1
        assert mc.total_failovers == 1
    
    def test_get_all_stats(self):
        mc = MetricsCollector(window_size=100)
        mc.record_request("provider1", 100.0, 100, 50, 0.005, success=True)
        mc.record_request("provider2", 200.0, 200, 100, 0.010, success=True)
        all_stats = mc.get_all_stats()
        assert "provider1" in all_stats["providers"]
        assert "provider2" in all_stats["providers"]
    
    def test_prometheus_export(self):
        mc = MetricsCollector(window_size=100)
        mc.record_request("test", 100.0, 100, 50, 0.005, success=True)
        prometheus = mc.export_prometheus()
        assert "router_total_requests" in prometheus
        assert "router_latency_p50" in prometheus
        assert "router_tokens_total" in prometheus


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

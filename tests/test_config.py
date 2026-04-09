"""
Test configuration loading and validation for AI API Failover Router.
"""

import os
import pytest
import tempfile
from pathlib import Path
import sys

# Add project root to path so src/ package imports work correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import AppConfig, ProviderConfig, HealthCheckConfig, MetricsConfig, RoutingStrategy, ServerConfig, get_config


class TestProviderConfig:
    def test_provider_config_minimal(self):
        config = ProviderConfig(
            name="test", 
            type="openai", 
            model="gpt-4o",
            base_url="https://api.test.com"
        )
        assert config.name == "test"
        assert config.type == "openai"
        assert config.model == "gpt-4o"
        assert config.timeout == 30.0
        assert config.max_retries == 3
    
    def test_provider_config_validation(self):
        with pytest.raises(Exception):
            ProviderConfig(type="openai", base_url="https://api.openai.com")


class TestHealthCheckConfig:
    def test_health_config_defaults(self):
        config = HealthCheckConfig()
        assert config.interval == 60.0
        assert config.failure_threshold == 3
        assert config.recovery_timeout == 30.0


class TestMetricsConfig:
    def test_metrics_config_defaults(self):
        config = MetricsConfig()
        assert config.enabled is True
        assert config.rolling_window_size == 1000


class TestRoutingStrategy:
    def test_routing_defaults(self):
        routing = RoutingStrategy()
        assert routing.strategy == "priority"
        assert routing.cost_threshold == 1.0


class TestServerConfig:
    def test_server_defaults(self):
        server = ServerConfig()
        assert server.host == "0.0.0.0"
        assert server.port == 8000


class TestAppConfig:
    def test_app_config_from_dict(self):
        config_data = {
            "providers": {"ollama": {"name": "ollama", "type": "ollama", "base_url": "http://localhost:11434", "model": "llama3"}},
            "health_check": {"interval": 60.0, "timeout": 10.0, "failure_threshold": 3},
            "metrics": {"enabled": True, "rolling_window_size": 1000},
            "routing": {"strategy": "priority", "fallback_chain": ["ollama"]},
            "server": {"host": "0.0.0.0", "port": 8000}
        }
        config = AppConfig(**config_data)
        assert len(config.providers) == 1
    
    def test_app_config_load_from_yaml(self):
        yaml_content = """
providers:
  ollama:
    name: "ollama"
    type: "ollama"
    base_url: "http://localhost:11434"
    model: "llama3"
health_check:
  interval: 60.0
  timeout: 10.0
  failure_threshold: 3
metrics:
  enabled: true
  rolling_window_size: 1000
routing:
  strategy: "priority"
  fallback_chain: ["ollama"]
server:
  host: "0.0.0.0"
  port: 8000
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        try:
            config = AppConfig.load_from_yaml(temp_path)
            assert len(config.providers) == 1
            assert config.providers["ollama"].base_url == "http://localhost:11434"
        finally:
            os.unlink(temp_path)
    
    def test_app_config_yaml_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            AppConfig.load_from_yaml("/nonexistent/config.yaml")


class TestGetConfig:
    def test_get_config_default_path(self):
        config_path = "/app/ml_project_0852/config.yaml"
        if os.path.exists(config_path):
            config = get_config(config_path)
            assert len(config.providers) >= 1
            assert config.server.port == 8000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

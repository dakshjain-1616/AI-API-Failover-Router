"""
Configuration system for AI API Failover Router.
Loads configuration from YAML file using Pydantic for validation.
"""

import os
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import yaml


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""
    name: str
    type: str  # ollama, openai, anthropic, deepseek, generic
    base_url: str
    api_key: Optional[str] = None
    model: str
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    cost_per_token: float = Field(default=0.0, description="Cost per token in USD")
    priority: int = Field(default=1, description="Provider priority (lower = higher priority)")
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    
    class Config:
        extra = 'allow'


class HealthCheckConfig(BaseModel):
    """Health check configuration."""
    interval: float = Field(default=60.0, description="Health check interval in seconds")
    timeout: float = Field(default=10.0, description="Health check timeout")
    failure_threshold: int = Field(default=3, description="Failures before circuit opens")
    recovery_timeout: float = Field(default=30.0, description="Time before attempting recovery")
    success_threshold: int = Field(default=2, description="Successes before circuit closes")


class MetricsConfig(BaseModel):
    """Metrics collection configuration."""
    enabled: bool = Field(default=True)
    rolling_window_size: int = Field(default=1000, description="Number of requests to track")
    latency_buckets: List[float] = Field(default=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0])
    prometheus_port: int = Field(default=9090)


class RoutingStrategy(BaseModel):
    """Routing strategy configuration."""
    strategy: str = Field(default="priority", description="Routing strategy: priority, cost, latency, health")
    fallback_chain: List[str] = Field(default=[], description="Ordered list of provider names for fallback")
    cost_threshold: float = Field(default=1.0, description="Maximum cost per request in USD")
    latency_threshold: float = Field(default=5.0, description="Maximum latency in seconds")
    default_timeout: float = Field(default=30.0, description="Default request timeout in seconds")


class ServerConfig(BaseModel):
    """Server configuration."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    log_level: str = Field(default="info")
    cors_origins: List[str] = Field(default=["*"])
    auth_enabled: bool = Field(default=False)
    auth_header: str = Field(default="Authorization")
    api_key: Optional[str] = Field(default=None, description="API key for authentication")
    rate_limit_requests: int = Field(default=100, description="Requests per minute")
    rate_limit_window: int = Field(default=60, description="Rate limit window in seconds")


class AppConfig(BaseModel):
    """Main application configuration."""
    providers: Dict[str, ProviderConfig]
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    routing: RoutingStrategy = Field(default_factory=RoutingStrategy)
    server: ServerConfig = Field(default_factory=ServerConfig)
    
    @classmethod
    def load_from_yaml(cls, path: str) -> "AppConfig":
        """Load configuration from YAML file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        with open(path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        return cls(**config_data)


def get_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Get application configuration.
    
    Args:
        config_path: Path to YAML config file. Defaults to config.yaml in project root.
    
    Returns:
        AppConfig instance
    """
    if config_path is None:
        # Default to config.yaml in project root
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        config_path = os.path.normpath(config_path)
    
    return AppConfig.load_from_yaml(config_path)


# Default configuration for testing
DEFAULT_CONFIG = {
    "providers": {
        "ollama": {
            "name": "ollama",
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "model": "llama3",
            "timeout": 30.0,
            "enabled": True
        },
        "openai": {
            "name": "openai",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-xxx",
            "model": "gpt-3.5-turbo",
            "timeout": 30.0,
            "enabled": True
        }
    },
    "health_check": {
        "interval": 60.0,
        "timeout": 10.0,
        "failure_threshold": 3,
        "recovery_timeout": 30.0,
        "success_threshold": 2
    },
    "metrics": {
        "enabled": True,
        "rolling_window_size": 1000
    },
    "routing": {
        "strategy": "priority",
        "fallback_chain": ["ollama", "openai"]
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8000,
        "log_level": "info"
    }
}

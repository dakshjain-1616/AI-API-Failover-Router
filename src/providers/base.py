"""
Base provider interface for AI API Failover Router.
Abstract base class defining the contract for all LLM providers.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import time


@dataclass
class ProviderResponse:
    """Normalized response from a provider."""
    content: str
    model: str
    usage: Dict[str, int]  # input_tokens, output_tokens, total_tokens
    latency_ms: float
    cost: float
    raw_response: Optional[Dict] = None
    error: Optional[str] = None


@dataclass
class HealthStatus:
    """Health status of a provider."""
    healthy: bool
    latency_ms: float = 0.0
    error: Optional[str] = None
    last_check: float = field(default_factory=time.time)


class BaseProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    All providers must implement:
    - complete(): Execute a completion request
    - health_check(): Check if provider is healthy
    - estimate_cost(): Estimate cost for a request
    - normalize_response(): Convert raw response to standard format
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize provider with configuration.
        
        Args:
            config: Provider configuration dict with name, type, base_url, api_key, model, etc.
        """
        self.config = config
        self.name = config.get('name', 'unknown')
        self.type = config.get('type', 'unknown')
        self.base_url = config.get('base_url', '')
        self.api_key = config.get('api_key', None)
        self.model = config.get('model', '')
        self.timeout = config.get('timeout', 30.0)
        self.max_retries = config.get('max_retries', 3)
        self.cost_per_token = config.get('cost_per_token', 0.0)
        self.priority = config.get('priority', 1)
        self.enabled = config.get('enabled', True)
    
    @abstractmethod
    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> ProviderResponse:
        """
        Execute a completion request.
        
        Args:
            messages: List of message dicts with role and content
            model: Model to use (overrides default)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            **kwargs: Additional provider-specific parameters
        
        Returns:
            ProviderResponse with normalized response data
        
        Raises:
            ProviderError: If request fails
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """
        Check if the provider is healthy.
        
        Returns:
            HealthStatus indicating provider health
        """
        pass
    
    @abstractmethod
    async def estimate_cost(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None
    ) -> float:
        """
        Estimate the cost of a request.
        
        Args:
            messages: List of message dicts
            max_tokens: Maximum tokens to generate
        
        Returns:
            Estimated cost in USD
        """
        pass
    
    @abstractmethod
    def normalize_response(
        self,
        raw_response: Dict,
        latency_ms: float
    ) -> ProviderResponse:
        """
        Convert raw provider response to normalized format.
        
        Args:
            raw_response: Raw response dict from provider API
            latency_ms: Request latency in milliseconds
        
        Returns:
            ProviderResponse with normalized data
        """
        pass
    
    def _count_tokens(self, text: str) -> int:
        """
        Simple token estimation (approximate).
        Uses character count as proxy (rough estimate).
        
        Args:
            text: Text to count tokens for
        
        Returns:
            Estimated token count
        """
        # Rough estimate: 1 token ≈ 4 characters
        return len(text) // 4
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, type={self.type}, enabled={self.enabled})"


class ProviderError(Exception):
    """Exception raised when a provider request fails."""
    
    def __init__(self, message: str, provider_name: str, status_code: Optional[int] = None):
        self.message = message
        self.provider_name = provider_name
        self.status_code = status_code
        super().__init__(f"[{provider_name}] {message}")

"""
DeepSeek provider implementation for AI API Failover Router.
"""

import asyncio
import time
import aiohttp
from typing import Any, Dict, List, Optional

from .base import BaseProvider, ProviderResponse, HealthStatus, ProviderError


class DeepSeekProvider(BaseProvider):
    """
    DeepSeek provider implementation.
    
    Supports DeepSeek chat models via their API.
    API: https://api.deepseek.com/v1/chat/completions
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_endpoint = f"{self.base_url}/chat/completions"
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> ProviderResponse:
        """Execute a completion request to DeepSeek."""
        start_time = time.time()
        model = model or self.model
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ProviderError(
                            f"HTTP {response.status}: {error_text}",
                            self.name,
                            response.status
                        )
                    
                    raw_response = await response.json()
                    latency_ms = (time.time() - start_time) * 1000
                    
                    return self.normalize_response(raw_response, latency_ms)
        
        except aiohttp.ClientError as e:
            raise ProviderError(f"Connection error: {str(e)}", self.name)
        except asyncio.TimeoutError:
            raise ProviderError(f"Request timeout after {self.timeout}s", self.name)
    
    async def health_check(self) -> HealthStatus:
        """Check if DeepSeek API is responsive."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                async with session.get(
                    f"{self.base_url}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5.0)
                ) as response:
                    if response.status == 200:
                        return HealthStatus(healthy=True, latency_ms=0.0)
                    else:
                        return HealthStatus(
                            healthy=False,
                            error=f"HTTP {response.status}"
                        )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))
    
    async def estimate_cost(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None
    ) -> float:
        """Estimate cost based on token count."""
        input_tokens = sum(self._count_tokens(m.get("content", "")) for m in messages)
        output_tokens = max_tokens or 100
        total_tokens = input_tokens + output_tokens
        return total_tokens * self.cost_per_token
    
    def normalize_response(
        self,
        raw_response: Dict,
        latency_ms: float
    ) -> ProviderResponse:
        """Convert DeepSeek response to normalized format."""
        choice = raw_response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        
        usage = raw_response.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
        
        cost = total_tokens * self.cost_per_token
        
        return ProviderResponse(
            content=content,
            model=raw_response.get("model", self.model),
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens
            },
            latency_ms=latency_ms,
            cost=cost,
            raw_response=raw_response
        )

"""
Anthropic provider implementation for AI API Failover Router.
"""

import asyncio
import time
import aiohttp
from typing import Any, Dict, List, Optional

from .base import BaseProvider, ProviderResponse, HealthStatus, ProviderError


class AnthropicProvider(BaseProvider):
    """
    Anthropic provider implementation.
    
    Supports Claude models via Anthropic API.
    API: https://api.anthropic.com/v1/messages
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_endpoint = f"{self.base_url}/messages"
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> ProviderResponse:
        """Execute a completion request to Anthropic."""
        start_time = time.time()
        model = model or self.model
        
        # Convert OpenAI-style messages to Anthropic format
        system_message = None
        anthropic_messages = []
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "system" and system_message is None:
                system_message = content
            else:
                anthropic_messages.append({"role": role, "content": content})
        
        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
            "stream": stream,
        }
        
        if system_message:
            payload["system"] = system_message
        
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
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
        """Check if Anthropic API is responsive."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "x-api-key": self.api_key or "",
                    "anthropic-version": "2023-06-01"
                }
                
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
        """Convert Anthropic response to normalized format."""
        content = ""
        if raw_response.get("content"):
            for item in raw_response["content"]:
                if item.get("type") == "text":
                    content += item.get("text", "")
        
        usage = raw_response.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
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

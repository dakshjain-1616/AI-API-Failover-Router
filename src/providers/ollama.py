"""
Ollama provider implementation for AI API Failover Router.
"""

import asyncio
import time
import aiohttp
from typing import Any, Dict, List, Optional

from .base import BaseProvider, ProviderResponse, HealthStatus, ProviderError


class OllamaProvider(BaseProvider):
    """
    Ollama provider implementation.
    
    Ollama provides local LLM inference with models like llama3, mistral, etc.
    API: http://localhost:11434/api/chat
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_endpoint = f"{self.base_url}/api/chat"
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> ProviderResponse:
        """Execute a completion request to Ollama."""
        start_time = time.time()
        model = model or self.model
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
            }
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_endpoint,
                    json=payload,
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
        """Check if Ollama is running and responsive."""
        try:
            start_time = time.time()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/version",
                    timeout=aiohttp.ClientTimeout(total=5.0)
                ) as response:
                    latency_ms = (time.time() - start_time) * 1000
                    if response.status == 200:
                        return HealthStatus(healthy=True, latency_ms=latency_ms)
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
        """Ollama is free (local), so cost is 0."""
        return 0.0
    
    def normalize_response(
        self,
        raw_response: Dict,
        latency_ms: float
    ) -> ProviderResponse:
        """Convert Ollama response to normalized format."""
        message = raw_response.get("message", {})
        content = message.get("content", "")
        
        # Ollama doesn't provide token counts in chat API, estimate
        input_tokens = sum(self._count_tokens(m.get("content", "")) for m in raw_response.get("messages", []))
        output_tokens = self._count_tokens(content)
        
        return ProviderResponse(
            content=content,
            model=raw_response.get("model", self.model),
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            },
            latency_ms=latency_ms,
            cost=0.0,
            raw_response=raw_response
        )

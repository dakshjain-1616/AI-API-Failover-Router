"""
Test provider implementations for AI API Failover Router.
Uses unittest.mock for aiohttp mocking with proper async context manager support.
"""

import asyncio
import pytest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.providers.ollama import OllamaProvider
from src.providers.openai import OpenAIProvider
from src.providers.anthropic import AnthropicProvider
from src.providers.deepseek import DeepSeekProvider
from src.providers.generic import GenericProvider
from src.providers.base import ProviderResponse, HealthStatus


class MockResponse:
    """Mock aiohttp ClientResponse - works as async context manager."""
    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data
        self.latency_ms = 0.1
    
    async def json(self):
        return self._json_data
    
    async def text(self):
        return self._text_data
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        pass


class MockSession:
    """Mock aiohttp ClientSession - async context manager."""
    def __init__(self, response_to_return=None):
        self._response = response_to_return or MockResponse()
    
    def post(self, url, **kwargs):
        """Return response directly - it's already an async context manager."""
        return self._response
    
    def get(self, url, **kwargs):
        """Return response directly - it's already an async context manager."""
        return self._response
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        pass


class TestOllamaProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        config = {
            "name": "ollama",
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "model": "llama2",
            "timeout": 30.0
        }
        provider = OllamaProvider(config)
        
        mock_response = MockResponse(
            status=200,
            json_data={
                "message": {"role": "assistant", "content": "Hello!"},
                "usage": {"total_tokens": 10}
            }
        )
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            response = await provider.complete(
                messages=[{"role": "user", "content": "Hi"}],
                model="llama2"
            )
            
            assert response.content == "Hello!"
            assert response.model == "llama2"
    
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        config = {
            "name": "ollama",
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "model": "llama2"
        }
        provider = OllamaProvider(config)
        
        mock_response = MockResponse(status=200)
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            status = await provider.health_check()
            assert status.healthy is True
    
    def test_estimate_cost_free(self):
        config = {
            "name": "ollama",
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "model": "llama2"
        }
        provider = OllamaProvider(config)
        
        cost = asyncio.run(provider.estimate_cost(
            messages=[{"role": "user", "content": "test"}],
            max_tokens=100
        ))
        assert cost == 0.0  # Ollama is free


class TestOpenAIProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        config = {
            "name": "openai",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "test-key",
            "timeout": 30.0,
            "cost_per_token": 0.00001
        }
        provider = OpenAIProvider(config)
        
        mock_response = MockResponse(
            status=200,
            json_data={
                "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
                "usage": {"total_tokens": 10}
            }
        )
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            response = await provider.complete(
                messages=[{"role": "user", "content": "Hi"}],
                model="gpt-4o"
            )
            
            assert response.content == "Hello!"
            assert response.model == "gpt-4o"
    
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        config = {
            "name": "openai",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "test-key"
        }
        provider = OpenAIProvider(config)
        
        mock_response = MockResponse(status=200)
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            status = await provider.health_check()
            assert status.healthy is True
    
    def test_estimate_cost(self):
        config = {
            "name": "openai",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "test-key",
            "cost_per_token": 0.00001
        }
        provider = OpenAIProvider(config)
        
        cost = asyncio.run(provider.estimate_cost(
            messages=[{"role": "user", "content": "test"}],
            max_tokens=100
        ))
        assert cost > 0.0


class TestAnthropicProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        config = {
            "name": "anthropic",
            "type": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model": "claude-3-sonnet",
            "api_key": "test-key",
            "timeout": 30.0
        }
        provider = AnthropicProvider(config)
        
        mock_response = MockResponse(
            status=200,
            json_data={
                "content": [{"type": "text", "text": "Hello!"}],
                "usage": {"input_tokens": 5, "output_tokens": 5}
            }
        )
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            response = await provider.complete(
                messages=[{"role": "user", "content": "Hi"}],
                model="claude-3-sonnet"
            )
            
            assert response.content == "Hello!"
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        config = {
            "name": "anthropic",
            "type": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model": "claude-3-sonnet",
            "api_key": "test-key"
        }
        provider = AnthropicProvider(config)
        
        mock_response = MockResponse(status=200)
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            status = await provider.health_check()
            assert status.healthy is True


class TestDeepSeekProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        config = {
            "name": "deepseek",
            "type": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "test-key",
            "timeout": 30.0
        }
        provider = DeepSeekProvider(config)
        
        mock_response = MockResponse(
            status=200,
            json_data={
                "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
                "usage": {"total_tokens": 10}
            }
        )
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            response = await provider.complete(
                messages=[{"role": "user", "content": "Hi"}],
                model="deepseek-chat"
            )
            
            assert response.content == "Hello!"


class TestGenericProvider:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        config = {
            "name": "generic",
            "type": "generic",
            "base_url": "https://api.example.com/v1",
            "model": "custom-model",
            "api_key": "test-key",
            "timeout": 30.0
        }
        provider = GenericProvider(config)
        
        mock_response = MockResponse(
            status=200,
            json_data={
                "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
                "usage": {"total_tokens": 10}
            }
        )
        mock_session = MockSession(mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            response = await provider.complete(
                messages=[{"role": "user", "content": "Hi"}],
                model="custom-model"
            )
            
            assert response.content == "Hello!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

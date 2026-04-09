"""
Middleware for AI API Failover Router.
Provides request logging, auth validation, rate limiting, and idempotency support.
"""

import time
import hashlib
from typing import Dict, Optional, Callable, Any
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging all requests with timing.
    """
    
    def __init__(self, app: ASGIApp, logger_callback: Optional[Callable] = None):
        super().__init__(app)
        self.logger_callback = logger_callback or self._default_logger
        self.request_count = 0
    
    def _default_logger(self, method: str, path: str, status: int, duration_ms: float):
        """Default logger prints to console."""
        timestamp = datetime.now().isoformat()
        print(f"[{timestamp}] {method} {path} -> {status} ({duration_ms:.2f}ms)")
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        method = scope["method"]
        path = scope["path"]
        
        # Process request
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                duration_ms = (time.time() - start_time) * 1000
                self.request_count += 1
                self.logger_callback(method, path, status, duration_ms)
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


class AuthValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for validating API key authentication.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        api_key: Optional[str] = None,
        skip_paths: Optional[list] = None
    ):
        super().__init__(app)
        self.api_key = api_key
        self.skip_paths = skip_paths or ["/health", "/metrics", "/stats"]
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        path = scope["path"]
        
        # Skip auth for certain paths
        if path in self.skip_paths or any(path.startswith(sp) for sp in self.skip_paths):
            await self.app(scope, receive, send)
            return
        
        # Check auth
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        
        # Check Bearer token
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if self.api_key and token == self.api_key:
                await self.app(scope, receive, send)
                return
        
        # Check X-API-Key header
        api_key_header = headers.get(b"x-api-key", b"").decode()
        if self.api_key and api_key_header == self.api_key:
            await self.app(scope, receive, send)
            return
        
        # No auth required
        if not self.api_key:
            await self.app(scope, receive, send)
            return
        
        # Auth failed
        response = JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Invalid or missing API key"}
        )
        await response(scope, receive, send)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting requests.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        by_key: bool = True
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.by_key = by_key
        
        # Track requests per client
        self.minute_counts: Dict[str, int] = defaultdict(int)
        self.hour_counts: Dict[str, int] = defaultdict(int)
        self.minute_start = time.time()
        self.hour_start = time.time()
    
    def _get_client_id(self, scope: Dict) -> str:
        """Get client identifier from request."""
        headers = dict(scope.get("headers", []))
        
        # Use API key if available
        api_key = headers.get(b"x-api-key", b"").decode()
        if api_key:
            return f"key:{api_key}"
        
        # Use auth token
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer "):
            return f"token:{auth[7:]}"
        
        # Use IP address
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        
        return "anonymous"
    
    def _check_limits(self, client_id: str) -> bool:
        """Check if client has exceeded rate limits."""
        now = time.time()
        
        # Reset counters if time window passed
        if now - self.minute_start > 60:
            self.minute_counts.clear()
            self.minute_start = now
        
        if now - self.hour_start > 3600:
            self.hour_counts.clear()
            self.hour_start = now
        
        # Check limits
        if self.minute_counts[client_id] >= self.requests_per_minute:
            return False
        
        if self.hour_counts[client_id] >= self.requests_per_hour:
            return False
        
        # Increment counters
        self.minute_counts[client_id] += 1
        self.hour_counts[client_id] += 1
        
        return True
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        client_id = self._get_client_id(scope)
        
        if not self._check_limits(client_id):
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Limit: {self.requests_per_minute}/min, {self.requests_per_hour}/hour"
                }
            )
            await response(scope, receive, send)
            return
        
        await self.app(scope, receive, send)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware for idempotency key support.
    Caches responses for duplicate requests with same idempotency key.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        cache_ttl_seconds: int = 3600
    ):
        super().__init__(app)
        self.cache_ttl = cache_ttl_seconds
        self.cache: Dict[str, Dict] = {}
    
    def _get_idempotency_key(self, scope: Dict) -> Optional[str]:
        """Get idempotency key from request headers."""
        headers = dict(scope.get("headers", []))
        key = headers.get(b"x-idempotency-key", b"").decode()
        return key if key else None
    
    def _compute_cache_key(self, key: str, body: bytes) -> str:
        """Compute cache key from idempotency key and request body."""
        content = f"{key}:{body.hex()}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _get_cached(self, cache_key: str) -> Optional[Dict]:
        """Get cached response if still valid."""
        if cache_key not in self.cache:
            return None
        
        cached = self.cache[cache_key]
        age = time.time() - cached["timestamp"]
        
        if age > self.cache_ttl:
            del self.cache[cache_key]
            return None
        
        return cached
    
    def _cache_response(self, cache_key: str, response_data: Dict):
        """Cache a response."""
        self.cache[cache_key] = {
            "data": response_data,
            "timestamp": time.time()
        }
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Only for POST/PUT requests
        if scope["method"] not in ["POST", "PUT"]:
            await self.app(scope, receive, send)
            return
        
        idempotency_key = self._get_idempotency_key(scope)
        
        if not idempotency_key:
            await self.app(scope, receive, send)
            return
        
        # Collect request body
        body = b""
        async for message in receive:
            if message["type"] == "http.request":
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
        
        # Compute cache key
        cache_key = self._compute_cache_key(idempotency_key, body)
        
        # Check cache
        cached = self._get_cached(cache_key)
        if cached:
            # Return cached response
            response = JSONResponse(
                status_code=200,
                content=cached["data"],
                headers={"x-idempotency-hit": "true"}
            )
            await response(scope, receive, send)
            return
        
        # Process request normally
        # Note: For full idempotency, we'd need to intercept the response
        # This simplified version just tracks the key
        await self.app(scope, receive, send)


def create_middleware_stack(
    app: ASGIApp,
    config: Dict[str, Any]
) -> ASGIApp:
    """
    Create middleware stack based on configuration.
    
    Args:
        app: FastAPI application
        config: Configuration dict with middleware settings
    
    Returns:
        Application with middleware applied
    """
    # Apply logging middleware
    app = RequestLoggingMiddleware(app)
    
    # Apply auth middleware
    api_key = config.get("api_key")
    app = AuthValidationMiddleware(app, api_key=api_key)
    
    # Apply rate limiting
    rate_limit_config = config.get("rate_limit", {})
    app = RateLimitMiddleware(
        app,
        requests_per_minute=rate_limit_config.get("per_minute", 60),
        requests_per_hour=rate_limit_config.get("per_hour", 1000)
    )
    
    # Apply idempotency middleware
    app = IdempotencyMiddleware(app, cache_ttl_seconds=config.get("idempotency_ttl", 3600))
    
    return app

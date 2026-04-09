"""
Pytest configuration for AI API Failover Router tests.
Configures pytest-asyncio for async test support.
"""

import pytest

# pytest.ini configures asyncio_mode = auto
# No need to manually load pytest-asyncio plugin here

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the asyncio event loop."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
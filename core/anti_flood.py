import asyncio
import random
import logging
from functools import wraps
from typing import Callable, Any
from config import settings

logger = logging.getLogger(__name__)

async def human_delay(min_seconds: float = None, max_seconds: float = None) -> float:
    """Sleep for a randomized duration to simulate human actions."""
    low = min_seconds if min_seconds is not None else settings.min_delay
    high = max_seconds if max_seconds is not None else settings.max_delay
    
    if low > high:
        low, high = high, low
        
    delay = random.uniform(low, high)
    logger.debug(f"Sleeping for {delay:.2f} seconds...")
    await asyncio.sleep(delay)
    return delay

def handle_flood_wait(max_retries: int = 3):
    """Decorator to catch Pyrogram / Telethon FloodWait exceptions and auto-retry."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            retries = 0
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Check for Pyrogram FloodWait or Telethon FloodWait error attributes
                    err_name = e.__class__.__name__
                    if "FloodWait" in err_name:
                        raw_wait = getattr(e, "value", None) or getattr(e, "seconds", None) or getattr(e, "x", None)
                        wait_seconds = 60
                        if raw_wait is not None:
                            try:
                                wait_seconds = int(raw_wait) + 2
                            except (ValueError, TypeError):
                                wait_seconds = 62
                        logger.warning(
                            f"Telegram FloodWait caught! Waiting for {wait_seconds}s before retrying... "
                            f"(Attempt {retries + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_seconds)
                        retries += 1
                    else:
                        raise e
            return await func(*args, **kwargs)
        return wrapper
    return decorator

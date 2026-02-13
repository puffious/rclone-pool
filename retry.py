"""
Retry logic with exponential backoff for rclone operations.
Part of v0.2 Robustness features.
"""

import time
import logging
from typing import Callable, Any, Optional
from functools import wraps

log = logging.getLogger('rclonepool')


class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, 
                 max_delay: float = 60.0, exponential_base: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base


def retry_with_backoff(config: Optional[RetryConfig] = None):
    """
    Decorator for retrying operations with exponential backoff.
    
    Usage:
        @retry_with_backoff(RetryConfig(max_retries=5))
        def my_operation():
            # ... code that might fail ...
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < config.max_retries:
                        delay = min(
                            config.base_delay * (config.exponential_base ** attempt),
                            config.max_delay
                        )
                        log.warning(
                            f"Operation {func.__name__} failed (attempt {attempt + 1}/{config.max_retries + 1}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        log.error(
                            f"Operation {func.__name__} failed after {config.max_retries + 1} attempts: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


def retry_operation(operation: Callable, config: Optional[RetryConfig] = None,
                   operation_name: str = "operation") -> Any:
    """
    Retry an operation with exponential backoff (functional approach).
    
    Args:
        operation: Callable to retry
        config: Retry configuration
        operation_name: Name for logging
        
    Returns:
        Result of the operation
        
    Raises:
        The last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(config.max_retries + 1):
        try:
            return operation()
        except Exception as e:
            last_exception = e
            
            if attempt < config.max_retries:
                delay = min(
                    config.base_delay * (config.exponential_base ** attempt),
                    config.max_delay
                )
                log.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{config.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                log.error(
                    f"{operation_name} failed after {config.max_retries + 1} attempts: {e}"
                )
    
    raise last_exception

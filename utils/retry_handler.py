"""Shared retry handler for batch operations with configurable strategies."""

from typing import Optional, Callable, Any
from dataclasses import dataclass
import asyncio
import random


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int
    base_delay: float
    backoff_factor: float  # 2 for exponential, 3 for aggressive
    jitter: bool = True
    custom_delays: Optional[list[float]] = None  # Override with custom delay schedule

    def calculate_delay(self, retry_count: int) -> float:
        """Calculate delay for given retry count."""
        # Use custom delays if provided
        if self.custom_delays and retry_count <= len(self.custom_delays):
            delay = self.custom_delays[retry_count - 1]
        else:
            # Fall back to exponential backoff
            delay = self.base_delay * (self.backoff_factor ** (retry_count - 1))

        # Add jitter to prevent synchronized retries
        if self.jitter:
            delay *= random.uniform(0.8, 1.2)

        return delay


# Predefined retry strategies
RETRY_STRATEGIES = {
    'recaptcha': RetryConfig(
        max_retries=5,
        base_delay=5.0,
        backoff_factor=3.0,
        custom_delays=[5, 15, 30, 45, 60]  # Custom progression: 5s → 15s → 30s → 45s → 60s
    ),
    'server_error': RetryConfig(
        max_retries=3,
        base_delay=2.0,
        backoff_factor=2.0  # Exponential: 2s → 4s → 8s
    ),
    'default': RetryConfig(
        max_retries=2,
        base_delay=1.0,
        backoff_factor=2.0  # Exponential: 1s → 2s
    )
}


class RetryHandler:
    """Centralized retry logic for batch operations."""

    @staticmethod
    def classify_error(error: Exception) -> str:
        """
        Classify error type for retry strategy selection.

        Args:
            error: The exception to classify

        Returns:
            Strategy name ('recaptcha', 'server_error', or 'default')
        """
        error_str = str(error)

        # Check for reCAPTCHA errors (403 with recaptcha keyword)
        if '403' in error_str and 'recaptcha' in error_str.lower():
            return 'recaptcha'

        # Check for server errors (500+)
        elif '500' in error_str:
            return 'server_error'

        # Default strategy for other errors
        else:
            return 'default'

    @staticmethod
    async def retry_with_backoff(
        func: Callable,
        error_type: str = 'default',
        logger = None,
        on_retry: Optional[Callable[[int, float, str], None]] = None
    ) -> Any:
        """
        Execute function with retry logic based on error type.

        Args:
            func: Async function to execute
            error_type: Type of error to determine retry strategy ('recaptcha', 'server_error', 'default')
            logger: Optional logger for debugging
            on_retry: Callback for progress updates (retry_count, delay, error_msg)

        Returns:
            Result from the function if successful

        Raises:
            The last exception if all retries are exhausted
        """
        config = RETRY_STRATEGIES.get(error_type, RETRY_STRATEGIES['default'])
        retry_count = 0
        last_error = None

        while retry_count <= config.max_retries:
            try:
                # Attempt execution
                return await func()

            except Exception as e:
                last_error = e

                # Classify the error to potentially adjust strategy
                detected_type = RetryHandler.classify_error(e)

                # Don't retry non-retryable errors
                if detected_type == 'default' and retry_count >= config.max_retries:
                    break

                # Increment retry count
                retry_count += 1
                if retry_count > config.max_retries:
                    break

                # Calculate delay for this retry
                delay = config.calculate_delay(retry_count)

                # Notify callback for progress tracking
                if on_retry:
                    on_retry(retry_count, delay, str(e))

                # Log retry attempt
                if logger:
                    logger.warning(
                        f"Retry {retry_count}/{config.max_retries} "
                        f"after {delay:.1f}s for {detected_type}: {str(e)[:100]}"
                    )

                # Wait before retry
                await asyncio.sleep(delay)

        # All retries exhausted, raise the last error
        if last_error:
            raise last_error
        else:
            raise RuntimeError("Retry logic failed without capturing error")

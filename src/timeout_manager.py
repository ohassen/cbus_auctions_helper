"""Timeout management for long-running workflows."""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TimeoutManager:
    """Manages workflow timeout to prevent exceeding maximum runtime limits."""

    def __init__(self, max_minutes: int, buffer_minutes: int = 2):
        """Initialize timeout manager.

        Args:
            max_minutes: Maximum allowed runtime in minutes
            buffer_minutes: Buffer time before hard timeout (default: 2 minutes)
        """
        self.max_minutes = max_minutes
        self.buffer_minutes = buffer_minutes
        self.start_time = datetime.now()
        self._timed_out = False

    @property
    def elapsed_minutes(self) -> float:
        """Get elapsed time in minutes since start."""
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        return elapsed_seconds / 60

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds since start."""
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def remaining_minutes(self) -> float:
        """Get remaining time in minutes before timeout."""
        return max(0, self.max_minutes - self.elapsed_minutes)

    def is_approaching_timeout(self) -> bool:
        """Check if we're approaching the timeout threshold.

        Returns:
            True if elapsed time >= (max_minutes - buffer_minutes)
        """
        threshold = self.max_minutes - self.buffer_minutes
        approaching = self.elapsed_minutes >= threshold

        if approaching and not self._timed_out:
            logger.warning(
                f"Approaching {self.max_minutes}-minute timeout "
                f"(elapsed: {self.elapsed_minutes:.1f} min)"
            )
            self._timed_out = True

        return approaching

    def is_exceeded(self) -> bool:
        """Check if maximum runtime has been exceeded.

        Returns:
            True if elapsed time >= max_minutes
        """
        return self.elapsed_minutes >= self.max_minutes

    def get_timeout_message(self) -> str:
        """Get a formatted timeout warning message.

        Returns:
            Message describing the timeout situation
        """
        return (
            f"Workflow stopped after {self.elapsed_minutes:.1f} minutes "
            f"to stay within {self.max_minutes}-minute limit"
        )

    def log_status(self, phase: str = ""):
        """Log current timeout status.

        Args:
            phase: Optional phase name to include in log message
        """
        phase_str = f" ({phase})" if phase else ""
        logger.info(
            f"Timeout status{phase_str}: "
            f"{self.elapsed_minutes:.1f}/{self.max_minutes} min elapsed, "
            f"{self.remaining_minutes:.1f} min remaining"
        )

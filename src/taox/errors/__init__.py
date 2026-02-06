"""Error handling for taox.

Provides error translation and human-friendly error messages.
"""

from taox.errors.translator import (
    ErrorCategory,
    TranslatedError,
    format_error_for_display,
    is_retryable,
    translate_error,
)

__all__ = [
    "ErrorCategory",
    "TranslatedError",
    "translate_error",
    "format_error_for_display",
    "is_retryable",
]

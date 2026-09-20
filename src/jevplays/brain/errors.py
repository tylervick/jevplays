"""Errors the loop reacts to. Kept SDK-free so loop.py never imports typesafe_sdk."""


class BrainUnavailable(RuntimeError):
    """TypeSafe could not answer after the SDK's own retries. The loop pauses, never presses."""

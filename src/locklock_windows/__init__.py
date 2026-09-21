"""Windows platform implementation for LockLock.

Modules keep Win32 imports lazy so shared tests can validate state and recovery
logic on non-Windows CI runners.
"""

WINDOWS_MINIMUM_RELEASE = "Windows 11 x64"

__all__ = ["WINDOWS_MINIMUM_RELEASE"]

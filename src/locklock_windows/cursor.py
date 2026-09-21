"""Global Windows cursor hiding is unavailable.

ShowCursor modifies a calling thread's display count, not every application.
Keep a no-op recovery interface without making an unsupported capability claim.
"""
class WindowsCursorController:
    def hide(self) -> None:
        raise NotImplementedError("Global Windows cursor hiding is unsupported")

    def show(self) -> None:
        pass

    def close(self) -> None:
        pass

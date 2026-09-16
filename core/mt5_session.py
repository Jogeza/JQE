"""Process-wide MT5 lifecycle authority; contains no broker SDK dependencies."""

from threading import RLock


class MT5SessionAuthority:
    def __init__(self) -> None:
        self.lock = RLock()
        self._owner: object | None = None
        self._active = False

    def reserve(self, owner: object) -> bool:
        with self.lock:
            if self._owner is not None and self._owner is not owner:
                return False
            self._owner = owner
            self._active = False
            return True

    def activate(self, owner: object) -> None:
        with self.lock:
            if self._owner is not owner:
                raise RuntimeError("MT5 session ownership unavailable")
            self._active = True

    def owns(self, owner: object) -> bool:
        with self.lock:
            return self._owner is owner

    def is_active(self, owner: object) -> bool:
        with self.lock:
            return self._owner is owner and self._active is True

    def invalidate(self) -> None:
        with self.lock:
            self._active = False
            self._owner = None

    def deactivate(self, owner: object) -> None:
        with self.lock:
            if self._owner is owner:
                self._active = False


mt5_session = MT5SessionAuthority()

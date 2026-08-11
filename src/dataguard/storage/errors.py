"""Content-safe audit storage failures."""

from __future__ import annotations

class StorageError(Exception):
    __slots__ = ()
    _code = "storage_unavailable"
    _message = "The configured local experiment database is unavailable."

    def __init__(self) -> None:
        super().__init__(self._message)

    @property
    def code(self) -> str: return self._code

    @property
    def message(self) -> str: return self._message

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        raise AttributeError("storage errors are fixed")

    def __repr__(self) -> str:
        return "StorageError()"

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class AuditQueryError(Exception):
    __slots__ = ()
    _code = "invalid_request"
    _message = "The request does not match the DataGuard API contract."

    def __init__(self) -> None:
        super().__init__(self._message)

    @property
    def code(self) -> str: return self._code

    @property
    def message(self) -> str: return self._message

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        raise AttributeError("query errors are fixed")

    def __repr__(self) -> str:
        return "AuditQueryError()"

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}

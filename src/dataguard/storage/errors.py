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


class _FixedStorageBoundaryError(Exception):
    __slots__ = ()
    _code = "internal_error"
    _message = "DataGuard could not complete the request."

    def __init__(self) -> None: super().__init__(self._message)
    @property
    def code(self) -> str: return self._code
    @property
    def message(self) -> str: return self._message
    def __str__(self) -> str: return self._message
    def __repr__(self) -> str: return f"{type(self).__name__}()"
    def as_dict(self) -> dict[str, str]: return {"code": self._code, "message": self._message}
    def __setattr__(self, name: str, value: object) -> None:
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        raise AttributeError("storage boundary errors are fixed")


class RunNotFoundError(_FixedStorageBoundaryError):
    _code = "run_not_found"
    _message = "The requested evaluation run does not exist."


class ReportNotReadyError(_FixedStorageBoundaryError):
    _code = "report_not_ready"
    _message = "A report is available only when the evaluation run is completed."


class ReportUnavailableError(_FixedStorageBoundaryError):
    _code = "report_unavailable"
    _message = "The failed or interrupted evaluation run cannot produce a report."


class RunStateError(_FixedStorageBoundaryError):
    pass


class ReportValidationError(_FixedStorageBoundaryError):
    _code = "experiment_manifest_mismatch"
    _message = "The dataset, models, storage profile, or locked settings do not match the manifest."

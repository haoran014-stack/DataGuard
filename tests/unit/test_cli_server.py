from pathlib import Path

import dataguard.cli as cli_module
from dataguard.cli import main
import dataguard.server as server_module
from dataguard.server import application_factory
from dataguard.vector_index import StoredIndexErrorCode, VectorIndexStoreError


ROOT = Path(__file__).resolve().parents[2]


def test_unified_validate_command_reuses_closed_stage1_validation(capsys):
    assert main(["--project-root", str(ROOT), "validate"]) == 0
    assert '"issue_count":0' in capsys.readouterr().out


def test_artifact_command_dependency_failure_is_minimized(monkeypatch, capsys):
    monkeypatch.setenv("DATAGUARD_OLLAMA_BASE_URL", "http://127.0.0.1:1")
    assert main(["--project-root", str(ROOT), "build-index"]) == 1
    output = capsys.readouterr().out
    assert "artifact_preparation_failed" in output
    assert "127.0.0.1" not in output


def test_build_index_does_not_treat_corrupt_artifact_as_missing(monkeypatch, capsys):
    class CorruptStore:
        def __init__(self, *_args):
            pass

        def read(self):
            raise VectorIndexStoreError(StoredIndexErrorCode.CORRUPT)

    class NetworkMustNotStart:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("network adapter must not be constructed")

    monkeypatch.setattr(cli_module, "VectorIndexStore", CorruptStore)
    monkeypatch.setattr(cli_module, "OllamaClient", NetworkMustNotStart)
    assert main(["--project-root", str(ROOT), "build-index"]) == 1
    assert "artifact_preparation_failed" in capsys.readouterr().out


def test_server_factory_constructs_six_routes_without_startup_io(monkeypatch):
    monkeypatch.setenv("DATAGUARD_PROJECT_ROOT", str(ROOT))
    app = application_factory()
    assert len(app.routes) == 6


def test_server_bind_is_local_by_default_and_gateway_only_under_opt_in(monkeypatch):
    calls = []
    monkeypatch.setattr(server_module.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    server_module.main()
    assert calls[-1]["host"] == "127.0.0.1"
    monkeypatch.setenv("DATAGUARD_ALLOW_CONTAINER_HOST_GATEWAY", "true")
    monkeypatch.setenv("DATAGUARD_OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    server_module.main()
    assert calls[-1]["host"] == "0.0.0.0"

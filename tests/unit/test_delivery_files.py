from pathlib import Path
import re
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_compose_topology_and_api_hardening_are_closed():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text("utf-8"))
    assert set(compose["services"]) == {"api", "postgres"}
    api = compose["services"]["api"]
    assert api["read_only"] is True
    assert api["cap_drop"] == ["ALL"]
    assert api["security_opt"] == ["no-new-privileges:true"]
    assert "./artifacts:/app/artifacts:ro" in api["volumes"]
    assert not any("docker.sock" in value for value in api["volumes"])
    assert api["extra_hosts"] == ["host.docker.internal:host-gateway"]
    assert api["ports"] == ["127.0.0.1:${DATAGUARD_API_PORT:-8000}:8000"]
    assert api["environment"]["DATAGUARD_PROFILE"] == "${DATAGUARD_PROFILE:-evidence}"
    assert compose["services"]["postgres"]["volumes"] == [
        "dataguard-postgres:/var/lib/postgresql/data"]


def test_example_environment_declares_default_api_host_port():
    lines = (ROOT / ".env.example").read_text("utf-8").splitlines()
    assert lines.count("DATAGUARD_API_PORT=8000") == 1
    assert lines.count("DATAGUARD_PROFILE=evidence") == 1


def test_docker_context_excludes_local_state_secrets_and_nonruntime_sources():
    lines = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
    assert lines[0] == "**"
    assert {line for line in lines if line.startswith("!")} == {
        "!Dockerfile", "!src/", "!src/**", "!data/", "!data/**", "!docs/",
        "!docs/contracts/", "!docs/contracts/**", "!requirements/",
        "!requirements/runtime-linux.lock",
    }
    for forbidden in (".env", "artifacts", "reports", "tests", "secrets/",
                      "private.key", "certificate.pem", "identity.p12", "identity.pfx"):
        assert not any(line == f"!{forbidden}" or line.startswith(f"!{forbidden}/")
                       for line in lines)


def test_demo_artifact_states_overwrite_and_http_timeouts_are_closed():
    value = (ROOT / "scripts/demo.ps1").read_text("utf-8")
    assert "[switch]$OverwriteArtifacts" in value
    assert "[ValidateRange(1,65535)]" in value
    assert "[int]$ApiPort = 8000" in value
    assert "$env:DATAGUARD_API_PORT = [string]$ApiPort" in value
    assert '$apiBaseUri = "http://127.0.0.1:$ApiPort"' in value
    assert "http://127.0.0.1:8000" not in value
    assert "$indexExists -and $manifestExists" in value
    assert "-not $indexExists -and -not $manifestExists" in value
    assert "Exactly one prepared artifact exists" in value
    assert "@('build-index', '--overwrite')" in value
    assert "@('generate-manifest', '--overwrite')" in value
    assert "$health = $null" in value
    http_lines = [line for line in value.splitlines()
                  if "Invoke-RestMethod" in line or "Invoke-WebRequest" in line]
    assert http_lines
    assert all("-TimeoutSec" in line for line in http_lines)
    assert all("$apiBaseUri" in line for line in http_lines)
    assert "docker compose down -v" not in value


def test_dockerfile_uses_only_hashed_dependency_install_and_nonroot_runtime():
    value = (ROOT / "Dockerfile").read_text("utf-8")
    assert "--require-hashes" in value
    assert "pip install --no-cache-dir --no-deps" not in value
    assert "USER dataguard" in value
    assert 'CMD ["python", "-m", "dataguard.server"]' in value


def test_platform_locks_are_fully_hashed_closed_and_cover_direct_pins():
    runtime = (ROOT / "requirements/runtime-linux.lock").read_text("utf-8")
    dev = (ROOT / "requirements/dev-linux.lock").read_text("utf-8")
    windows = (ROOT / "requirements/dev-windows.lock").read_text("utf-8")
    for value in (runtime, dev, windows):
        lowered = value.lower()
        for forbidden in ("http://", "https://", "--editable", "-e ",
                          "--index-url", "--extra-index-url", "--trusted-host", " @ "):
            assert forbidden not in lowered
        for line in value.splitlines():
            if not line or line.startswith("#") or line.startswith("-r "):
                continue
            assert re.fullmatch(
                r"[a-z0-9-]+==[^ ]+ --hash=sha256:[a-f0-9]{64}", line)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    for requirement in project["project"]["dependencies"]:
        name, version = requirement.replace("[binary]", "").split("==")
        assert f"{name.lower()}=={version} " in runtime.lower()
        assert f"{name.lower()}=={version} " in windows.lower()
    assert "pytest==9.1.1 " in dev
    assert "pytest==9.1.1 " in windows

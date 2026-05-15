"""New tests for WinLocalProcessSpawner.

Those adapted from JupyterHub's Linux spawner tests 
reside in test_winlocalprocessspawner_ported.py.
"""

import asyncio
import subprocess
import sys

import pytest
import winlocalprocessspawner.winlocalprocessspawner as wps


class DummyLog:
    """Capture log calls for assertions."""

    def __init__(self):
        """Initializes DummyLog with an empty list of messages."""
        self.messages = []

    def info(self, msg, *args):
        self.messages.append(("info", msg, args))

    def warning(self, msg, *args):
        self.messages.append(("warning", msg, args))

    def error(self, msg, *args):
        self.messages.append(("error", msg, args))


class DummyToken:
    """Simple token stub that records detach calls."""

    def __init__(self, value):
        """Initializes a DummyToken with given value, and which has not been detached."""
        self.value = value
        self.detached = 0

    def Detach(self):  # noqa: N802
        """Increment the detach counter."""
        self.detached += 1


class DummyHandleFactory:
    """Pywin32 HANDLE factory stub."""

    def __init__(self):
        """Initializes DummyHandleFactory with an empty list of created tokens."""
        self.created = []

    def __call__(self, value):
        token = DummyToken(value)
        self.created.append(token)
        return token


class DummyUser:
    """Minimal user object used by tests."""

    def __init__(self, name, auth_state):
        """Initializes a DummyUser with given name and auth_state."""
        self.name = name
        self._auth_state = auth_state

    async def get_auth_state(self):
        return self._auth_state


class DummyDB:
    """Capture whether commit is called."""

    def __init__(self):
        """Initializes DummyDB with 0 commit calls."""
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1


class DummyServer:
    """Server state holder."""

    def __init__(self):
        """Initializes DummyServer with no set ip and port."""
        self.ip = None
        self.port = None


def make_spawner(auth_state=None):
    """Create a lightweight spawner instance with required attributes only."""
    spawner = wps.WinLocalProcessSpawner.__new__(wps.WinLocalProcessSpawner)
    spawner.user = DummyUser("alice", auth_state)
    spawner.cmd = ["python", "-m", "jupyterhub_singleuser"]
    spawner.shell_cmd = []
    spawner.log = DummyLog()
    spawner.notebook_dir = ""
    spawner.popen_kwargs = {"creationflags": 1}
    spawner.ip = "127.0.0.1"
    spawner.server = DummyServer()
    spawner.db = DummyDB()
    spawner.get_env = lambda: {"APPDATA": "C:/base/appdata", "JUPYTERHUB_API_TOKEN": "token"}
    spawner.get_args = lambda: ["--debug"]
    return spawner


def test_user_env_sets_user_name():
    """user_env should inject USER from the jupyterhub user."""
    spawner = wps.WinLocalProcessSpawner.__new__(wps.WinLocalProcessSpawner)
    spawner.user = type("User", (), {"name": "alice"})()

    env = spawner.user_env({"A": "B"})

    assert env["USER"] == "alice"
    assert env["A"] == "B"


def test_get_env_keeps_selected_windows_vars(monkeypatch):
    """get_env should copy selected Windows environment values from os.environ."""
    spawner = wps.WinLocalProcessSpawner.__new__(wps.WinLocalProcessSpawner)

    monkeypatch.setattr(wps.LocalProcessSpawner, "get_env", lambda self: {"BASE": "1"})
    monkeypatch.setenv("SYSTEMROOT", "C:/Windows")
    monkeypatch.setenv("APPDATA", "C:/Users/alice/AppData/Roaming")

    env = spawner.get_env()

    assert env["BASE"] == "1"
    assert env["SYSTEMROOT"] == "C:/Windows"
    assert env["APPDATA"] == "C:/Users/alice/AppData/Roaming"


def test_start_uses_userprofile_as_cwd_when_notebook_dir_unset(monkeypatch):
    """Start should prefer USERPROFILE from user env when notebook_dir is empty."""
    spawner = make_spawner(auth_state={"auth_token": 123})
    handle_factory = DummyHandleFactory()

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])

    monkeypatch.setattr(wps, "random_port", lambda: 9999)
    monkeypatch.setattr(wps.pywintypes, "HANDLE", handle_factory)
    monkeypatch.setattr(
        wps.win32profile,
        "CreateEnvironmentBlock",
        lambda token, _inherit: {
            "APPDATA": "C:/Users/alice/AppData/Roaming",
            "USERPROFILE": "C:/Users/alice",
            "PUBLIC": "C:/Users/Public",
        },
    )
    monkeypatch.setattr(wps, "PopenAsUser", fake_popen)

    ip, port = asyncio.run(spawner.start())

    assert (ip, port) == ("127.0.0.1", 9999)
    assert spawner.pid > 0

    cmd, kwargs = popen_calls[0]
    assert cmd == ["python", "-m", "jupyterhub_singleuser", "--debug"]
    assert kwargs["cwd"] == "C:/Users/alice"
    assert kwargs["creationflags"] == 1
    assert kwargs["env"]["APPDATA"] == "C:/Users/alice/AppData/Roaming"

    created_token = handle_factory.created[0]
    assert created_token.value == 123
    assert created_token.detached == 1


class TestApplyUserEnvOverrides:
    """Unit tests for WinLocalProcessSpawner._apply_user_env_overrides."""

    def _make_spawner(self):
        spawner = wps.WinLocalProcessSpawner.__new__(wps.WinLocalProcessSpawner)
        return spawner

    def test_merges_user_env_when_token_and_user_env_present(self):
        """User env vars should be merged into env when both token and user_env are given."""
        spawner = self._make_spawner()
        env = {"EXISTING": "value"}
        user_env = {"APPDATA": "C:/Users/alice/AppData", "USERPROFILE": "C:/Users/alice"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, user_env, token)

        assert env["APPDATA"] == "C:/Users/alice/AppData"
        assert env["USERPROFILE"] == "C:/Users/alice"
        assert env["EXISTING"] == "value"

    def test_does_not_merge_user_env_when_token_is_none(self):
        """User env vars should not be merged when token is None."""
        spawner = self._make_spawner()
        env = {"EXISTING": "value"}
        user_env = {"APPDATA": "C:/Users/alice/AppData"}

        spawner._apply_user_env_overrides(env, user_env, token=None)

        assert "APPDATA" not in env

    def test_does_not_merge_user_env_when_user_env_is_none(self):
        """Nothing should be merged when user_env is None."""
        spawner = self._make_spawner()
        env = {"EXISTING": "value"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, user_env=None, token=token)

        assert env == {"EXISTING": "value"}

    def test_sets_userprofile_to_public_when_appdata_missing(self):
        """USERPROFILE should be set to PUBLIC when APPDATA is absent from user_env."""
        spawner = self._make_spawner()
        env = {"PUBLIC": "C:/Users/Public"}
        user_env = {"PUBLIC": "C:/Users/Public"}  # no APPDATA
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, user_env, token)

        assert env["USERPROFILE"] == "C:/Users/Public"

    def test_userprofile_falls_back_to_env_public_when_user_env_has_no_public(self):
        """USERPROFILE fallback should use env PUBLIC if user_env has no PUBLIC key."""
        spawner = self._make_spawner()
        env = {"PUBLIC": "C:/Users/Public"}
        user_env = {"HOMEPATH": "\\Users\\alice"}  # non-empty, no APPDATA, no PUBLIC
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, user_env, token)

        assert env["USERPROFILE"] == "C:/Users/Public"

    def test_userprofile_empty_string_when_no_public_anywhere(self):
        """USERPROFILE should be empty string when PUBLIC is absent everywhere."""
        spawner = self._make_spawner()
        env = {}
        user_env = {"HOMEPATH": "\\Users\\alice"}  # non-empty, no APPDATA, no PUBLIC
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, user_env, token)

        assert env["USERPROFILE"] == ""

    def test_does_not_override_userprofile_when_appdata_present(self):
        """USERPROFILE should not be overridden when APPDATA is present in user_env."""
        spawner = self._make_spawner()
        env = {}
        user_env = {"APPDATA": "C:/Users/alice/AppData", "USERPROFILE": "C:/Users/alice"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, user_env, token)

        assert env["USERPROFILE"] == "C:/Users/alice"


def test_start_falls_back_to_tempdir_when_user_env_load_fails(monkeypatch):
    """Start should use mkdtemp as cwd when user profile environment cannot be loaded."""
    spawner = make_spawner(auth_state=None)
    spawner.get_env = lambda: {"APPDATA": "", "JUPYTERHUB_API_TOKEN": "token"}

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])

    monkeypatch.setattr(wps, "random_port", lambda: 10001)
    monkeypatch.setattr(
        wps.win32profile,
        "CreateEnvironmentBlock",
        lambda token, _inherit: (_ for _ in ()).throw(RuntimeError("no profile")),
    )
    monkeypatch.setattr(wps, "mkdtemp", lambda: "C:/tmp/fallback-dir")
    monkeypatch.setattr(wps, "PopenAsUser", fake_popen)

    ip, port = asyncio.run(spawner.start())

    assert (ip, port) == ("127.0.0.1", 10001)
    assert popen_calls[0][1]["cwd"] == "C:/tmp/fallback-dir"

    warning_logs = [entry for entry in spawner.log.messages if entry[0] == "warning"]
    assert warning_logs
    assert "Failed to load user environment" in warning_logs[0][1]


def test_start_permission_error_logs_and_detaches_token(monkeypatch):
    """Start should log permission errors and detach token before re-raising."""
    spawner = make_spawner(auth_state={"auth_token": 456})
    handle_factory = DummyHandleFactory()

    monkeypatch.setattr(wps, "random_port", lambda: 7777)
    monkeypatch.setattr(wps.pywintypes, "HANDLE", handle_factory)
    monkeypatch.setattr(
        wps.win32profile,
        "CreateEnvironmentBlock",
        lambda token, _inherit: {
            "APPDATA": "C:/Users/alice/AppData/Roaming",
            "USERPROFILE": "C:/Users/alice",
            "PUBLIC": "C:/Users/Public",
        },
    )
    monkeypatch.setattr(
        wps, "PopenAsUser", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError())
    )
    monkeypatch.setattr(wps.shutil, "which", lambda script: f"C:/resolved/{script}")

    with pytest.raises(PermissionError):
        asyncio.run(spawner.start())

    error_logs = [entry for entry in spawner.log.messages if entry[0] == "error"]
    assert error_logs
    assert "Permission denied trying to run" in error_logs[0][1]

    created_token = handle_factory.created[0]
    assert created_token.detached == 1

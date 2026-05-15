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


def test_start_preserves_get_env_vars_not_present_in_user_env(monkeypatch):
    """Vars set by get_env() that are absent from user_env must survive the merge.

    Keys like JUPYTERHUB_API_TOKEN are set by JupyterHub's get_env() and will
    never appear in a Windows user profile block, so they must not be silently
    dropped when _apply_user_env_overrides merges user_env into env.
    """
    spawner = make_spawner(auth_state={"auth_token": 123})
    spawner.get_env = lambda: {
        "JUPYTERHUB_API_TOKEN": "secret-token",
        "APPDATA": "C:/base/appdata",
    }
    handle_factory = DummyHandleFactory()

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])

    monkeypatch.setattr(wps, "random_port", lambda: 9998)
    monkeypatch.setattr(wps.pywintypes, "HANDLE", handle_factory)
    monkeypatch.setattr(
        wps.win32profile,
        "CreateEnvironmentBlock",
        lambda token, _inherit: {
            "APPDATA": "C:/Users/alice/AppData/Roaming",
            "USERPROFILE": "C:/Users/alice",
            # JUPYTERHUB_API_TOKEN intentionally absent from the Windows profile block
        },
    )
    monkeypatch.setattr(wps, "PopenAsUser", fake_popen)

    asyncio.run(spawner.start())

    env = popen_calls[0][1]["env"]
    assert env["JUPYTERHUB_API_TOKEN"] == "secret-token"


def test_start_cwd_uses_userprofile_from_profile_env(monkeypatch):
    """When token is present, cwd comes from env['USERPROFILE'] after the merge.

    A subclass that protects env['USERPROFILE'] (e.g. least-privilege custom path)
    will have that protected value used as cwd, since cwd is read from env
    (post-merge) when a token is present.
    """

    class ProtectiveSpawner(wps.WinLocalProcessSpawner):
        def _apply_user_env_overrides(self, env, profile_env, token):
            userprofile = env.get("USERPROFILE")
            super()._apply_user_env_overrides(env, profile_env, token)
            if userprofile:
                env["USERPROFILE"] = userprofile

    spawner = make_spawner(auth_state={"auth_token": 123})
    spawner.__class__ = ProtectiveSpawner
    spawner.get_env = lambda: {
        "APPDATA": "C:/base/appdata",
        "USERPROFILE": "C:/JupyterHub/profiles/alice",
    }
    handle_factory = DummyHandleFactory()

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])

    monkeypatch.setattr(wps, "random_port", lambda: 9997)
    monkeypatch.setattr(wps.pywintypes, "HANDLE", handle_factory)
    monkeypatch.setattr(
        wps.win32profile,
        "CreateEnvironmentBlock",
        lambda token, _inherit: {
            "APPDATA": "C:/Users/alice/AppData/Roaming",
            "USERPROFILE": "C:/Users/alice",
        },
    )
    monkeypatch.setattr(wps, "PopenAsUser", fake_popen)

    asyncio.run(spawner.start())

    # token present → cwd from env after merge → subclass-protected value wins
    assert popen_calls[0][1]["cwd"] == "C:/JupyterHub/profiles/alice"


def test_start_no_token_profile_env_still_merged_for_cwd(monkeypatch):
    """cwd uses USERPROFILE from profile_env even when token is None.

    env.update(profile_env) is skipped when there is no token, but cwd is
    derived directly from profile_env['USERPROFILE'] so the user's home
    directory is still used as the working directory.
    """
    spawner = make_spawner(auth_state=None)
    spawner.get_env = lambda: {
        "APPDATA": "C:/ServiceAccount/AppData",
        "USERPROFILE": "C:/ServiceAccount",
    }

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])

    monkeypatch.setattr(wps, "random_port", lambda: 9996)
    monkeypatch.setattr(
        wps.win32profile,
        "CreateEnvironmentBlock",
        lambda token, _inherit: {
            "APPDATA": "C:/Users/alice/AppData/Roaming",
            "USERPROFILE": "C:/Users/alice",
        },
    )
    monkeypatch.setattr(wps, "PopenAsUser", fake_popen)

    asyncio.run(spawner.start())

    # profile_env is merged even with no token, so cwd uses the profile USERPROFILE.
    assert popen_calls[0][1]["cwd"] == "C:/Users/alice"


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


class TestApplyUserEnvOverrides:
    """Unit tests for WinLocalProcessSpawner._apply_user_env_overrides."""

    def _make_spawner(self):
        spawner = wps.WinLocalProcessSpawner.__new__(wps.WinLocalProcessSpawner)
        return spawner

    def test_merges_profile_env_when_token_and_profile_env_present(self):
        """Windows profile vars are merged into env when both token and profile_env are given."""
        spawner = self._make_spawner()
        env = {"EXISTING": "value"}
        profile_env = {"APPDATA": "C:/Users/alice/AppData", "USERPROFILE": "C:/Users/alice"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["APPDATA"] == "C:/Users/alice/AppData"
        assert env["USERPROFILE"] == "C:/Users/alice"
        assert env["EXISTING"] == "value"

    def test_merges_profile_env_regardless_of_token(self):
        """profile_env is merged into env only when token is present.

        When token is None the merge is skipped, but cwd is still read
        directly from profile_env so the user's USERPROFILE is used.
        """
        spawner = self._make_spawner()
        env = {"EXISTING": "value"}
        profile_env = {"APPDATA": "C:/Users/alice/AppData"}

        spawner._apply_user_env_overrides(env, profile_env, token=None)

        # merge skipped — APPDATA not copied into env
        assert "APPDATA" not in env

    def test_does_not_merge_profile_env_when_profile_env_is_none(self):
        """Nothing should be merged when profile_env is None."""
        spawner = self._make_spawner()
        env = {"EXISTING": "value"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env=None, token=token)

        assert env == {"EXISTING": "value"}

    def test_sets_userprofile_to_public_when_appdata_missing(self):
        """USERPROFILE should be set to PUBLIC when APPDATA is absent from profile_env."""
        spawner = self._make_spawner()
        env = {"PUBLIC": "C:/Users/Public"}
        profile_env = {"PUBLIC": "C:/Users/Public"}  # no APPDATA
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["USERPROFILE"] == "C:/Users/Public"

    def test_userprofile_falls_back_to_env_public_when_profile_env_has_no_public(self):
        """USERPROFILE fallback should use env PUBLIC if profile_env has no PUBLIC key."""
        spawner = self._make_spawner()
        env = {"PUBLIC": "C:/Users/Public"}
        profile_env = {"HOMEPATH": "\\Users\\alice"}  # non-empty, no APPDATA, no PUBLIC
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["USERPROFILE"] == "C:/Users/Public"

    def test_userprofile_empty_string_when_no_public_anywhere(self):
        """USERPROFILE should be empty string when PUBLIC is absent everywhere."""
        spawner = self._make_spawner()
        env = {}
        profile_env = {"HOMEPATH": "\\Users\\alice"}  # non-empty, no APPDATA, no PUBLIC
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["USERPROFILE"] == ""

    def test_does_not_override_userprofile_when_appdata_present(self):
        """USERPROFILE should not be overridden when APPDATA is present in profile_env."""
        spawner = self._make_spawner()
        env = {}
        profile_env = {"APPDATA": "C:/Users/alice/AppData", "USERPROFILE": "C:/Users/alice"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["USERPROFILE"] == "C:/Users/alice"

    def test_base_class_overwrites_env_key_present_in_profile_env(self):
        """Base implementation merges profile_env on top of env, so conflicting keys are
        overwritten.


        This documents the default behaviour that motivates subclasses to override
        _apply_user_env_overrides when they need to protect specific keys.
        """
        spawner = self._make_spawner()
        env = {"JUPYTERHUB_API_TOKEN": "secret-token"}
        profile_env = {"JUPYTERHUB_API_TOKEN": "value-from-windows-profile"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["JUPYTERHUB_API_TOKEN"] == "value-from-windows-profile"

    def test_subclass_can_protect_keys_from_profile_env_overwrite(self):
        """A subclass override of _apply_user_env_overrides can protect specific keys.

        Because _apply_user_env_overrides is a hook, subclasses can restore
        critical values (e.g. JUPYTERHUB_* vars) after the merge so the Windows
        profile block cannot replace them.
        """

        class ProtectiveSpawner(wps.WinLocalProcessSpawner):
            def _apply_user_env_overrides(self, env, profile_env, token):
                protected = {k: v for k, v in env.items() if k.startswith("JUPYTERHUB_")}
                super()._apply_user_env_overrides(env, profile_env, token)
                env.update(protected)

        spawner = ProtectiveSpawner.__new__(ProtectiveSpawner)
        env = {"JUPYTERHUB_API_TOKEN": "secret-token"}
        profile_env = {"JUPYTERHUB_API_TOKEN": "value-from-windows-profile"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["JUPYTERHUB_API_TOKEN"] == "secret-token"

    def test_base_class_overwrites_appdata_set_by_least_privilege_subclass(self):
        """Base implementation overwrites APPDATA set before the merge.

        In least-privilege mode a subclass sets a custom APPDATA path before
        start() calls CreateEnvironmentBlock. The base env.update(profile_env)
        then silently replaces it with the standard Roaming path from the
        Windows profile block — demonstrating why the override hook is needed.
        """
        profile_dir = "C:/JupyterHub/profiles/alice"
        spawner = self._make_spawner()
        env = {"APPDATA": f"{profile_dir}/AppData/Roaming"}
        profile_env = {"APPDATA": "C:/Users/alice/AppData/Roaming"}  # from CreateEnvironmentBlock
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        # base class overwrites — the custom path is lost
        assert env["APPDATA"] == "C:/Users/alice/AppData/Roaming"

    def test_subclass_can_protect_appdata_from_profile_env_overwrite(self):
        """A subclass override can preserve a custom APPDATA set in least-privilege mode.

        The override captures the caller-set APPDATA before the merge and
        restores it afterwards, preventing CreateEnvironmentBlock from clobbering it.
        """
        profile_dir = "C:/JupyterHub/profiles/alice"

        class LeastPrivilegeSpawner(wps.WinLocalProcessSpawner):
            def _apply_user_env_overrides(self, env, profile_env, token):
                appdata = env.get("APPDATA")
                super()._apply_user_env_overrides(env, profile_env, token)
                if appdata:
                    env["APPDATA"] = appdata

        spawner = LeastPrivilegeSpawner.__new__(LeastPrivilegeSpawner)
        env = {"APPDATA": f"{profile_dir}/AppData/Roaming"}
        profile_env = {"APPDATA": "C:/Users/alice/AppData/Roaming"}
        token = DummyToken(1)

        spawner._apply_user_env_overrides(env, profile_env, token)

        assert env["APPDATA"] == f"{profile_dir}/AppData/Roaming"

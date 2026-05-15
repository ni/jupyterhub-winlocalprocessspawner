"""Windows-specific JupyterHub spawner for launching single-user servers as local processes."""

import os
import pipes
import shutil
from tempfile import mkdtemp

import pywintypes
import win32profile
from jupyterhub.spawner import LocalProcessSpawner
from jupyterhub.utils import random_port

from .win_utils import PopenAsUser


class WinLocalProcessSpawner(LocalProcessSpawner):
    """A Spawner that start single-user servers as local Windows processes.

    It uses the authentication token stored in the field 'auth_token' of the current
    auth_state. Its the Authenticator's job to fill the 'auth_token' with a valid Windows
    authentication token handle.
    """

    def user_env(self, env):
        """Augment environment of spawned process with user specific env variables."""
        env["USER"] = self.user.name
        return env

    def get_env(self):
        """Get the complete set of environment variables to be set in the spawned process."""
        win_env_keep = ["SYSTEMROOT", "APPDATA", "WINDIR", "USERPROFILE", "TEMP"]

        env = super().get_env()
        for key in win_env_keep:
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _apply_user_env_overrides(self, env, profile_env, token):
        """Merge the Windows user profile environment into the spawner-built env.

        Called after CreateEnvironmentBlock returns. Subclasses can override
        this method to protect specific keys in `env` from being overwritten
        by the profile block (e.g. custom APPDATA in least-privilege mode).

        :param env: The spawner-built environment dict from get_env(). Modified in place.
        :param profile_env: The Windows user profile env from CreateEnvironmentBlock, or None on failure.
        :param token: The Windows auth token, or None.
        """
        if token and profile_env:
            # Merge the Windows profile block into the spawner env.
            # Note: profile_env values overwrite any matching keys already in env.
            # Subclasses that need to protect specific keys (e.g. APPDATA set to a
            # custom profile directory) should snapshot those keys before calling
            # super() and restore them after.
            env.update(profile_env)
        if profile_env and "APPDATA" not in profile_env:
            # The profile loaded but has no APPDATA — the user profile directory is
            # not fully set up, so USERPROFILE would point at a non-writable default.
            # Fall back to the PUBLIC directory, which is always writable.
            env["USERPROFILE"] = profile_env.get("PUBLIC", env.get("PUBLIC", ""))

    async def start(self):
        """Start the single-user server."""
        self.port = random_port()
        cmd = []
        env = self.get_env()
        token = None

        cmd.extend(self.cmd)

        cmd.extend(self.get_args())

        if self.shell_cmd:
            # using shell_cmd (e.g. bash -c),
            # add our cmd list as the last (single) argument:
            cmd = self.shell_cmd + [" ".join(pipes.quote(s) for s in cmd)]

        self.log.info("Spawning %s", " ".join(pipes.quote(s) for s in cmd))

        auth_state = await self.user.get_auth_state()
        if auth_state:
            token = auth_state.get("auth_token")
            if token:
                token = pywintypes.HANDLE(token)

        profile_env = None
        cwd = None

        try:
            # Load the Windows user profile environment for the authenticated token.
            profile_env = win32profile.CreateEnvironmentBlock(token, False)
        except Exception as exc:
            self.log.warning("Failed to load user environment for %s: %s", self.user.name, exc)

        self._apply_user_env_overrides(env, profile_env, token)

        # On Posix, the cwd is set to ~ before spawning the singleuser server (preexec_fn).
        # Windows Popen doesn't have preexec_fn support, so we need to set cwd directly.
        if self.notebook_dir:
            cwd = os.getcwd()
        elif env.get("APPDATA"):
            cwd = env.get("USERPROFILE", mkdtemp())
        else:
            # Set CWD to a temp directory, since we failed to load the user profile
            cwd = mkdtemp()

        popen_kwargs = dict(
            token=token,
            cwd=cwd,
        )

        popen_kwargs.update(self.popen_kwargs)
        # don't let user config override env
        popen_kwargs["env"] = env
        try:
            self.proc = PopenAsUser(cmd, **popen_kwargs)
        except PermissionError:
            # use which to get abspath
            script = shutil.which(cmd[0]) or cmd[0]
            self.log.error(
                "Permission denied trying to run %r. Does %s have access to this file?",
                script,
                self.user.name,
            )
            if token:
                token.Detach()
            raise

        self.pid = self.proc.pid
        if token:
            token.Detach()

        if self.__class__ is not LocalProcessSpawner:
            # subclasses may not pass through return value of super().start,
            # relying on deprecated 0.6 way of setting ip, port,
            # so keep a redundant copy here for now.
            # A deprecation warning will be shown if the subclass
            # does not return ip, port.
            if self.ip:
                self.server.ip = self.ip
            self.server.port = self.port
            self.db.commit()

        return (self.ip or "127.0.0.1", self.port)

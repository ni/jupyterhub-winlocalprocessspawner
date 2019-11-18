import os
import sys
import pipes
import shutil
from tempfile import mkdtemp

from jupyterhub.spawner import LocalProcessSpawner
from jupyterhub.utils import random_port

import pywintypes
import win32profile

from .win_utils import PopenAsUser


class WinLocalProcessSpawner(LocalProcessSpawner):
    """
    A Spawner that start single-user servers as local Windows processes

    It uses the authentication token stored in the field 'auth_token' of the current
    auth_state. Its the Authenticator's job to fill the 'auth_token' with a valid Windows
    authentication token handle.
    """

    def user_env(self, env):
        """Augment environment of spawned process with user specific env variables."""
        env['USER'] = self.user.name
        return env

    def get_env(self):
        """Get the complete set of environment variables to be set in the spawned process."""
        win_env_keep = ['SYSTEMROOT', 'APPDATA', 'WINDIR', 'USERPROFILE', 'TEMP']

        env = super().get_env()
        for key in win_env_keep:
            if key in os.environ:
                env[key] = os.environ[key]
        return env

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
            cmd = self.shell_cmd + [' '.join(pipes.quote(s) for s in cmd)]

        self.log.info("Spawning %s", ' '.join(pipes.quote(s) for s in cmd))

        auth_state = await self.user.get_auth_state()
        if auth_state:
            token = pywintypes.HANDLE(auth_state['auth_token'])

        user_env = None
        cwd = None

        try:
            # Will load user variables, if the user profile is loaded
            user_env = win32profile.CreateEnvironmentBlock(token, False)
        except Exception as exc:
            self.log.warning("Failed to load user environment for %s: %s", self.user.name, exc)
        else:
            # Only load user environment if we hold a valid auth token
            if token:
                env.update(user_env)
            if not 'APPDATA' in user_env:
                #If the 'APPDATA' does not exist, the USERPROFILE points at the default
                #directory which is not writable. this changes the path over to public
                #documents, so at least its a writable location.
                user_env['USERPROFILE'] = user_env['PUBLIC']

        # On Posix, the cwd is set to ~ before spawning the singleuser server (preexec_fn).
        # Windows Popen doesn't have preexec_fn support, so we need to set cwd directly.
        if self.notebook_dir:
            cwd = os.getcwd()
        elif env['APPDATA']:
            cwd = user_env['USERPROFILE']
        else:
            # Set CWD to a temp directory, since we failed to load the user profile
            cwd = mkdtemp()

        popen_kwargs = dict(
            token=token,
            cwd=cwd,
        )

        popen_kwargs.update(self.popen_kwargs)
        # don't let user config override env
        popen_kwargs['env'] = env
        try:
            self.proc = PopenAsUser(cmd, **popen_kwargs)
        except PermissionError:
            # use which to get abspath
            script = shutil.which(cmd[0]) or cmd[0]
            self.log.error("Permission denied trying to run %r. Does %s have access to this file?",
                           script, self.user.name,
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

        return (self.ip or '127.0.0.1', self.port)

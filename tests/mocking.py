"""Ported from JupyterHub's tests/mocking.py.

- Remove Linux-specific library usage (pamela)
- Make MockSpawner use WinLocalProcessSpawner instead of Linux-specific LocalProcessSpawner.

Original description:

Mock utilities for testing.

Functions
---------
- mock_authenticate
- mock_check_account
- mock_open_session

Spawners
--------
- MockSpawner: based on LocalProcessSpawner
- SlowSpawner:
- NeverSpawner:
- BadSpawner:
- SlowBadSpawner
- FormSpawner

Other components
----------------
- MockPAMAuthenticator
- MockHub
- MockSingleUserServer
- StubSingleUserSpawner

- public_host
- public_url

"""

import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from tempfile import NamedTemporaryFile
from unittest import mock
from urllib.parse import urlparse

from jupyterhub import metrics, orm
from jupyterhub.app import JupyterHub
from jupyterhub.auth import Authenticator
from jupyterhub.singleuser import SingleUserNotebookApp
from jupyterhub.tests.utils import async_requests, public_url, ssl_setup
from jupyterhub.utils import random_port
from tornado.ioloop import IOLoop
from traitlets import Bool, Dict, default
from winlocalprocessspawner import WinLocalProcessSpawner


class MockSpawner(WinLocalProcessSpawner):
    """Base mock spawner.

    - disables user-switching that we need root permissions to do
    - spawns `jupyterhub.tests.mocksu` instead of a full single-user server
    """

    def user_env(self, env):
        """Adds HANDLER_ARGS to user_env."""
        env = super().user_env(env)
        if self.handler:
            env["HANDLER_ARGS"] = self.handler.request.query
        return env

    @default("cmd")
    def _cmd_default(self):
        return [sys.executable, "-m", "jupyterhub.tests.mocksu"]

    use_this_api_token = None

    def start(self):
        """Starts the MockSpawner."""
        if self.use_this_api_token:
            self.api_token = self.use_this_api_token
        elif self.will_resume:
            self.use_this_api_token = self.api_token
        return super().start()


class SlowSpawner(MockSpawner):
    """A spawner that takes a few seconds to start."""

    delay = 2
    _start_future = None

    async def start(self):
        """Starts the SlowSpawner."""
        (ip, port) = await super().start()
        if self._start_future is not None:
            await self._start_future
        else:
            await asyncio.sleep(self.delay)
        return ip, port

    async def stop(self):
        """Stops the SlowSpawner."""
        await asyncio.sleep(self.delay)
        await super().stop()


class NeverSpawner(MockSpawner):
    """A spawner that will never start."""

    @default("start_timeout")
    def _start_timeout_default(self):
        return 1

    def start(self):
        """Return a Future that will never finish."""
        return asyncio.Future()

    async def stop(self):
        """Stops the NeverSpawner."""
        pass

    async def poll(self):
        """Return exit code 0."""
        return 0


class BadSpawner(MockSpawner):
    """Spawner that fails immediately."""

    def start(self):
        """Raises an exception when trying to run the BadSpawner."""
        raise RuntimeError("I don't work!")


class SlowBadSpawner(MockSpawner):
    """Spawner that fails after a short delay."""

    async def start(self):
        """Raises an exception after some waiting."""
        await asyncio.sleep(0.5)
        raise RuntimeError("I don't work!")


class FormSpawner(MockSpawner):
    """A spawner that has an options form defined."""

    options_form = "IMAFORM"

    def options_from_form(self, form_data):
        """Extracts options from form data."""
        options = {"notspecified": 5}
        if "bounds" in form_data:
            options["bounds"] = [int(i) for i in form_data["bounds"]]
        if "energy" in form_data:
            options["energy"] = form_data["energy"][0]
        if "hello_file" in form_data:
            options["hello"] = form_data["hello_file"][0]

        if "illegal_argument" in form_data:
            raise ValueError("You are not allowed to specify 'illegal_argument'")
        return options


class FalsyCallableFormSpawner(FormSpawner):
    """A spawner that has a callable options form defined returning a falsy value."""

    @staticmethod
    def options_form(a, b):
        """Returns empty string."""
        return ""


class MockStructGroup:
    """Mock grp.struct_group."""

    def __init__(self, name, members, gid=1111):
        """Initializes MockStructGroup."""
        self.gr_name = name
        self.gr_mem = members
        self.gr_gid = gid


class MockStructPasswd:
    """Mock pwd.struct_passwd."""

    def __init__(self, name, gid=1111):
        """Initializes MockStructPasswd."""
        self.pw_name = name
        self.pw_gid = gid


class MockHub(JupyterHub):
    """Hub with various mock bits."""

    # disable some inherited traits with hardcoded values
    db_file = None
    last_activity_interval = 2
    log_datefmt = "%M:%S"

    @default("log_level")
    def _default_log_level(self):
        return 10

    # MockHub additional traits
    external_certs = Dict()

    def __init__(self, *args, **kwargs):
        """Initializes MockHub."""
        if "internal_certs_location" in kwargs:
            cert_location = kwargs["internal_certs_location"]
            kwargs["external_certs"] = ssl_setup(cert_location, "hub-ca")
        super().__init__(*args, **kwargs)

    @default("subdomain_host")
    def _subdomain_host_default(self):
        return os.environ.get("JUPYTERHUB_TEST_SUBDOMAIN_HOST", "")

    @default("bind_url")
    def _default_bind_url(self):
        if self.subdomain_host:
            port = urlparse(self.subdomain_host).port
        else:
            port = random_port()
        return "http://127.0.0.1:%i/@/space%%20word/" % (port,)

    @default("ip")
    def _ip_default(self):
        return "127.0.0.1"

    @default("port")
    def _port_default(self):
        if self.subdomain_host:
            port = urlparse(self.subdomain_host).port
            if port:
                return port
        return random_port()

    @default("authenticator_class")
    def _authenticator_class_default(self):
        return Authenticator

    @default("spawner_class")
    def _spawner_class_default(self):
        return MockSpawner

    def init_signal(self):
        """Does nothing."""
        pass

    def load_config_file(self, *args, **kwargs):
        """Does nothing."""
        pass

    def init_tornado_application(self):
        """Instantiate the tornado Application object."""
        super().init_tornado_application()
        # reconnect tornado_settings so that mocks can update the real thing
        self.tornado_settings = self.users.settings = self.tornado_application.settings

    def init_services(self):
        """Explicitly expire services before reinitializing.

        This only happens in tests because re-initialize
        does not occur in a real instance.
        """
        for service in self.db.query(orm.Service):
            self.db.expire(service)
        return super().init_services()

    test_clean_db = Bool(True)

    def init_db(self):
        """Ensure we start with a clean user list."""
        super().init_db()
        if self.test_clean_db:
            for user in self.db.query(orm.User):
                self.db.delete(user)
            for group in self.db.query(orm.Group):
                self.db.delete(group)
            self.db.commit()

    async def initialize(self, argv=None):
        """Initialize MockHub."""
        self.pid_file = NamedTemporaryFile(delete=False).name
        db_url = os.getenv("JUPYTERHUB_TEST_DB_URL")
        self.db_file = None
        if db_url:
            self.db_url = db_url
        else:
            # Keep only a closed temp file path so SQLite can reopen it on Windows.
            # In this case, self.db_file will store the path to the file
            db_file = NamedTemporaryFile(delete=False)
            self.db_file = db_file.name
            db_file.close()
            self.db_url = self.db_file
        if "mysql" in self.db_url:
            self.db_kwargs["connect_args"] = {"auth_plugin": "mysql_native_password"}
        await super().initialize([])

        # add an initial user
        user = self.db.query(orm.User).filter(orm.User.name == "user").first()
        if user is None:
            user = orm.User(name="user")
            self.db.add(user)
            self.db.commit()
            metrics.TOTAL_USERS.inc()

    def stop(self):
        "Stop the MockHub."
        super().stop()

        # run cleanup in a background thread
        # to avoid multiple eventloops in the same thread errors from asyncio

        def cleanup():
            asyncio.set_event_loop(asyncio.new_event_loop())
            loop = IOLoop.current()
            loop.run_sync(self.cleanup)
            loop.close()

        pool = ThreadPoolExecutor(1)
        f = pool.submit(cleanup)
        # wait for cleanup to finish
        f.result()
        pool.shutdown()

        # ignore the call that will fire in atexit
        self.cleanup = lambda: None
        if self.db_file and os.path.exists(self.db_file):
            os.remove(self.db_file)

    async def login_user(self, name):
        """Login a user by name, returning her cookies."""
        base_url = public_url(self)
        external_ca = None
        if self.internal_ssl:
            external_ca = self.external_certs["files"]["ca"]
        r = await async_requests.post(
            base_url + "hub/login",
            data={"username": name, "password": name},
            allow_redirects=False,
            verify=external_ca,
        )
        r.raise_for_status()
        assert r.cookies
        return r.cookies


# single-user-server mocking:


class MockSingleUserServer(SingleUserNotebookApp):
    """Mock-out problematic parts of single-user server when run in a thread.

    Currently:

    - disable signal handler
    """

    def init_signal(self):
        """Does nothing."""
        pass


class StubSingleUserSpawner(MockSpawner):
    """Spawner that starts a MockSingleUserServer in a thread."""

    @default("default_url")
    def _default_url(self):
        """Use a default_url that any jupyter server will provide.

        Should be:

        - authenticated, so we are testing auth
        - always available (i.e. in base ServerApp and NotebookApp
        """
        return "/api/status"

    _thread = None

    async def start(self):
        """Starts the StubSingleUserSpawner."""
        ip = self.ip = "127.0.0.1"
        port = self.port = random_port()
        env = self.get_env()
        args = self.get_args()
        evt = threading.Event()
        print(args, env)

        def _run():
            asyncio.set_event_loop(asyncio.new_event_loop())
            io_loop = IOLoop()
            io_loop.make_current()
            io_loop.add_callback(lambda: evt.set())

            with mock.patch.dict(os.environ, env):
                app = self._app = MockSingleUserServer()
                app.initialize(args)
                assert app.hub_auth.oauth_client_id
                assert app.hub_auth.api_token
                app.start()

        self._thread = threading.Thread(target=_run)
        self._thread.start()
        ready = evt.wait(timeout=3)
        assert ready
        return (ip, port)

    async def stop(self):
        """Stops the StubSingleUserSpawner."""
        self._app.stop()
        self._thread.join(timeout=30)
        assert not self._thread.is_alive()

    async def poll(self):
        """Returns result based on whether underlying thread is alive."""
        if self._thread is None:
            return 0
        if self._thread.is_alive():
            return None
        else:
            return 0

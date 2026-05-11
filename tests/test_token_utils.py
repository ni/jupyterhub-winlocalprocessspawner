import secrets
import string
from unittest import mock

import pytest
import win32net
import win32netcon
import win32security
import winlocalprocessspawner.token_utils as token_utils


class MockPyHandle:
    """Mock PyHANDLE class since it's not exported by pywin32."""

    def __init__(self, handle):
        """Initializes PyHANDLE with an integer handle value."""
        self.handle = handle

    def handle(self):
        return self.handle

    def Close(self):  # noqa: N802
        return None

    def Detach(self):  # noqa: N802
        self.Handle = None
        return self


@pytest.fixture
def test_service_user():
    """Sets up a temporary Windows local user that has service logon rights."""

    def _random_password(length=24):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    username = "wlpstest_" + secrets.token_hex(4)
    password = _random_password()

    user_info = {
        "name": username,
        "password": password,
        "priv": win32netcon.USER_PRIV_USER,
        "home_dir": None,
        "comment": "temporary pytest user",
        "flags": win32netcon.UF_SCRIPT,
        "script_path": None,
    }

    try:
        win32net.NetUserAdd(None, 1, user_info)

        # Get the user's SID
        sid = win32security.LookupAccountName(None, username)[0]
        policy_handle = win32security.LsaOpenPolicy(None, win32security.POLICY_ALL_ACCESS)

        # Grant SeServiceLogonRight
        win32security.LsaAddAccountRights(
            policy_handle,  # Local system
            sid,
            [win32security.SE_SERVICE_LOGON_NAME],
        )

        yield {"username": username, "password": password}
    finally:
        try:
            win32net.NetUserDel(None, username)
        except Exception:
            pass


class TestUnitTokenUtils:
    """Unit tests for token_utils."""

    def test_create_token_returns_token_if_logon_user_call_is_successful(self, monkeypatch):
        def mock_logon_user(*args):
            pyhandle = MockPyHandle(9999)
            return pyhandle

        monkeypatch.setattr(token_utils.win32security, "LogonUser", mock_logon_user)

        token = token_utils.create_service_token("test_user", "test_pass")
        assert token.handle == 9999

    def test_create_token_returns_none_and_logs_error_if_logon_user_yields_win32api_error(
        self, monkeypatch
    ):
        def mock_logon_user(*args):
            pyhandle = MockPyHandle(9999)
            return pyhandle

        def mock_get_last_error():
            return -1

        mock_logger = mock.Mock()

        monkeypatch.setattr(token_utils, "logger", mock_logger)
        monkeypatch.setattr(token_utils.win32security, "LogonUser", mock_logon_user)
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        token = token_utils.create_service_token("test_user", "test_pass")
        assert token is None
        mock_logger.error.assert_called()

    def test_create_token_returns_none_and_logs_error_if_logon_user_excepts(self, monkeypatch):
        def mock_logon_user(*args):
            import pywintypes

            raise pywintypes.error

        def mock_get_last_error():
            return -1

        mock_logger = mock.Mock()

        monkeypatch.setattr(token_utils, "logger", mock_logger)
        monkeypatch.setattr(token_utils.win32security, "LogonUser", mock_logon_user)
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        token = token_utils.create_service_token("test_user", "test_pass")
        assert token is None
        mock_logger.error.assert_called()


class TestIntegrationTokenUtils:
    """Integration tests token_utils."""

    def test_create_token_with_real_service_user_returns_valid_token(self, test_service_user):
        token = token_utils.create_service_token(
            test_service_user["username"],
            test_service_user["password"],
        )

        assert token is not None
        token.Close()

    def test_create_token_with_valid_username_and_invalid_password_returns_none(
        self, test_service_user
    ):
        token = token_utils.create_service_token(
            test_service_user["username"],
            test_service_user["password"] + "suffix_to_make_password_invalid",
        )

        assert token is None

    def test_create_token_with_nonexisting_username_returns_none(self):
        token = token_utils.create_service_token(
            "NonexistingUsername1234567654321",
            "dummy_password",
        )

        assert token is None

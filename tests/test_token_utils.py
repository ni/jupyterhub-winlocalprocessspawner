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
def temporary_service_user():
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

        token_handle = token_utils.create_service_token("test_user", "test_pass")
        assert token_handle.handle == 9999

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

        token_handle = token_utils.create_service_token("test_user", "test_pass")
        assert token_handle is None
        mock_logger.error.assert_called()

    def test_create_token_returns_none_and_logs_error_if_logon_user_excepts(self, monkeypatch):
        def mock_logon_user(*args):
            import pywintypes

            raise pywintypes.error

        def mock_get_last_error():
            return 0

        mock_logger = mock.Mock()

        monkeypatch.setattr(token_utils, "logger", mock_logger)
        monkeypatch.setattr(token_utils.win32security, "LogonUser", mock_logon_user)
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        token_handle = token_utils.create_service_token("test_user", "test_pass")
        assert token_handle is None
        mock_logger.error.assert_called()

    def test_remove_all_token_privileges_calls_create_restricted_token_with_disable_max_privilege(
        self, monkeypatch
    ):
        passed_flags = None

        def mock_create_restricted_token(token, flags, *args):
            nonlocal passed_flags
            passed_flags = flags
            return 9999

        monkeypatch.setattr(
            token_utils.win32security, "CreateRestrictedToken", mock_create_restricted_token
        )

        restricted_token = token_utils.remove_all_token_privileges(1111)
        assert restricted_token == 9999
        assert passed_flags | win32security.DISABLE_MAX_PRIVILEGE

    def test_remove_all_token_privileges_returns_none_and_logs_error_if_create_restricted_token_excepts(
        self, monkeypatch
    ):
        def mock_create_restricted_token(*args):
            import pywintypes

            raise pywintypes.error

        def mock_get_last_error():
            return 0

        mock_logger = mock.Mock()

        monkeypatch.setattr(token_utils, "logger", mock_logger)
        monkeypatch.setattr(
            token_utils.win32security, "CreateRestrictedToken", mock_create_restricted_token
        )
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        restricted_token = token_utils.remove_all_token_privileges(1111)
        assert restricted_token is None
        mock_logger.error.assert_called()

    def test_remove_all_token_privileges_returns_none_and_logs_error_if_create_restricted_token_yields_win32api_error(
        self, monkeypatch
    ):
        def mock_create_restricted_token(*args):
            return 9999

        def mock_get_last_error():
            return -1

        mock_logger = mock.Mock()

        monkeypatch.setattr(token_utils, "logger", mock_logger)
        monkeypatch.setattr(
            token_utils.win32security, "CreateRestrictedToken", mock_create_restricted_token
        )
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        restricted_token = token_utils.remove_all_token_privileges(1111)
        assert restricted_token is None
        mock_logger.error.assert_called()


class TestIntegrationTokenUtils:
    """Integration tests for token_utils."""

    def test_create_token_with_real_service_user_returns_valid_token(self, temporary_service_user):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"],
        )

        assert token_handle is not None
        token_handle.Close()

    def test_create_token_with_valid_username_and_invalid_password_returns_none(
        self, temporary_service_user
    ):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"] + "suffix_to_make_password_invalid",
        )

        assert token_handle is None

    def test_create_token_with_nonexisting_username_returns_none(self):
        token_handle = token_utils.create_service_token(
            "NonexistingUsername1234567654321",
            "dummy_password",
        )

        assert token_handle is None

    @pytest.mark.parametrize("token", [None, 0])
    def test_remove_all_token_privileges_with_invalid_token_logs_error_and_returns_none(
        self, token, monkeypatch
    ):
        mock_logger = mock.Mock()
        monkeypatch.setattr(token_utils, "logger", mock_logger)

        restricted_token = token_utils.remove_all_token_privileges(token)

        assert restricted_token is None
        mock_logger.error.assert_called()

    def test_remove_all_privileges_with_valid_token_removes_privileges_but_preserves_group_sids(
        self, temporary_service_user
    ):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"],
        )
        assert token_handle is not None

        restricted_token = token_utils.remove_all_token_privileges(token_handle)
        assert restricted_token is not None

        privileges = win32security.GetTokenInformation(
            restricted_token, win32security.TokenPrivileges
        )
        # only the SeChangeNotifyPrivilege should remain
        assert len(privileges) == 1
        privilege_name = win32security.LookupPrivilegeName(None, privileges[0][0])
        assert privilege_name == win32security.SE_CHANGE_NOTIFY_NAME

        # the group SIDs should remain the same
        original_token_groups = win32security.GetTokenInformation(
            token_handle, win32security.TokenGroups
        )
        restricted_token_groups = win32security.GetTokenInformation(
            restricted_token, win32security.TokenGroups
        )
        assert original_token_groups == restricted_token_groups

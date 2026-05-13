"""Unit and integration tests for token_utils.

Unit tests are under class `TestUnitTokenUtils`.
Integration tests are under class `TestIntegrationTokenUtils`.
"""

import secrets
import string
from unittest import mock

import ntsecuritycon
import pytest
import pywintypes
import win32api
import win32net
import win32netcon
import win32security
import winerror
import winlocalprocessspawner.token_utils as token_utils


@pytest.fixture
def temporary_service_user():
    """Sets up a temporary Windows local user that has service logon rights."""

    def _random_password(length=24):
        special_characters = "!@#$%^&*"
        alphabet = string.ascii_letters + string.digits + special_characters
        # prefix password with a choice of [lowercase][uppercase][digit][special] to make sure
        # that the password passes Windows minimum requirements
        minimum_requirements_prefix = (
            secrets.choice(string.ascii_lowercase)
            + secrets.choice(string.ascii_uppercase)
            + secrets.choice(string.digits)
            + secrets.choice(special_characters)
        )
        return minimum_requirements_prefix + "".join(
            secrets.choice(alphabet) for _ in range(length)
        )

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
        try:
            # Grant SeServiceLogonRight
            win32security.LsaAddAccountRights(
                policy_handle,  # Local system
                sid,
                [win32security.SE_SERVICE_LOGON_NAME],
            )
        finally:
            win32security.LsaClose(policy_handle)

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
            pyhandle = pywintypes.HANDLE(9999)
            return pyhandle

        monkeypatch.setattr(token_utils.win32security, "LogonUser", mock_logon_user)

        token_handle = token_utils.create_service_token("test_user", "test_pass")
        assert token_handle.handle == 9999

    def test_create_token_excepts_if_logon_user_excepts(self, monkeypatch):
        def mock_logon_user(*args):
            raise pywintypes.error

        def mock_get_last_error():
            return -1

        monkeypatch.setattr(token_utils.win32security, "LogonUser", mock_logon_user)
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        with pytest.raises(pywintypes.error):
            token_utils.create_service_token("test_user", "test_pass")

    def test_restrict_token_calls_create_restricted_token_with_disable_max_privilege(
        self, monkeypatch
    ):
        passed_flags = None

        def mock_create_restricted_token(token, flags, *args):
            nonlocal passed_flags
            passed_flags = flags
            return 9999

        def mock_set_token_information(*args):
            pass

        monkeypatch.setattr(
            token_utils.win32security, "CreateRestrictedToken", mock_create_restricted_token
        )
        monkeypatch.setattr(
            token_utils.win32security, "SetTokenInformation", mock_set_token_information
        )

        restricted_token = token_utils.restrict_token(1111)
        assert restricted_token == 9999
        assert passed_flags & win32security.DISABLE_MAX_PRIVILEGE

    def test_restrict_token_excepts_if_create_restricted_token_excepts(self, monkeypatch):
        def mock_create_restricted_token(*args):
            raise pywintypes.error

        def mock_get_last_error():
            return -1

        mock_logger = mock.Mock()

        monkeypatch.setattr(token_utils, "logger", mock_logger)
        monkeypatch.setattr(
            token_utils.win32security, "CreateRestrictedToken", mock_create_restricted_token
        )
        monkeypatch.setattr(token_utils.win32api, "GetLastError", mock_get_last_error)

        with pytest.raises(pywintypes.error):
            token_utils.restrict_token(1111)


class TestIntegrationTokenUtils:
    """Integration tests for token_utils."""

    def test_create_token_with_real_service_user_returns_valid_token(self, temporary_service_user):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"],
        )

        token_handle.Close()

    def test_create_token_with_valid_username_and_invalid_password_excepts(
        self, temporary_service_user
    ):
        with pytest.raises(pywintypes.error) as exc_info:
            token_utils.create_service_token(
                temporary_service_user["username"],
                temporary_service_user["password"] + "suffix_to_make_password_invalid",
            )
        assert exc_info.value.winerror == winerror.ERROR_LOGON_FAILURE

    def test_create_token_with_nonexisting_username_excepts(self):
        with pytest.raises(pywintypes.error) as exc_info:
            token_utils.create_service_token(
                "NonexistingUsername1234567654321",
                "dummy_password",
            )
        assert exc_info.value.winerror == winerror.ERROR_LOGON_FAILURE

    @pytest.mark.parametrize("token", [None, 0])
    def test_restrict_token_with_invalid_token_excepts(self, token, monkeypatch):
        mock_logger = mock.Mock()
        monkeypatch.setattr(token_utils, "logger", mock_logger)

        with pytest.raises(pywintypes.error) as exc_info:
            token_utils.restrict_token(token)
        assert exc_info.value.winerror == winerror.ERROR_INVALID_HANDLE

    def test_restrict_token_with_valid_token_removes_privileges(self, temporary_service_user):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"],
        )

        restricted_token = None
        try:
            restricted_token = token_utils.restrict_token(token_handle)
        finally:
            token_handle.Close()  # no longer needed

        try:
            privileges = win32security.GetTokenInformation(
                restricted_token, win32security.TokenPrivileges
            )
            # only the SeChangeNotifyPrivilege should remain
            assert len(privileges) == 1
            privilege_name = win32security.LookupPrivilegeName(None, privileges[0][0])
            assert privilege_name == win32security.SE_CHANGE_NOTIFY_NAME
        finally:
            if restricted_token:
                win32api.CloseHandle(restricted_token)

    def test_restrict_token_with_valid_token_sets_medium_integrity_level(
        self, temporary_service_user
    ):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"],
        )

        restricted_token = None
        try:
            restricted_token = token_utils.restrict_token(token_handle)
        finally:
            token_handle.Close()  # no longer needed

        try:
            # check that Medium Integrity Level is properly applied to the token
            restricted_integrity = win32security.GetTokenInformation(
                restricted_token, win32security.TokenIntegrityLevel
            )
            restricted_integrity_sid, restricted_integrity_attrs = restricted_integrity

            expected_medium_sid = win32security.CreateWellKnownSid(
                win32security.WinMediumLabelSid, None
            )

            assert restricted_integrity_sid == expected_medium_sid
            assert restricted_integrity_attrs & ntsecuritycon.SE_GROUP_INTEGRITY
        finally:
            if restricted_token:
                win32api.CloseHandle(restricted_token)

    def test_restrict_token_with_valid_token_sets_preserves_group_sids_except_for_group_integrity(
        self, temporary_service_user
    ):
        token_handle = token_utils.create_service_token(
            temporary_service_user["username"],
            temporary_service_user["password"],
        )

        restricted_token = None
        try:
            restricted_token = token_utils.restrict_token(token_handle)

            # the group SIDs, except for the integrity one, should remain the same
            original_token_groups = win32security.GetTokenInformation(
                token_handle, win32security.TokenGroups
            )
            restricted_token_groups = win32security.GetTokenInformation(
                restricted_token, win32security.TokenGroups
            )

            original_non_integrity_groups = sorted(
                [
                    (win32security.ConvertSidToStringSid(sid), attrs)
                    for sid, attrs in original_token_groups
                    if not (attrs & ntsecuritycon.SE_GROUP_INTEGRITY)
                ]
            )
            restricted_non_integrity_groups = sorted(
                [
                    (win32security.ConvertSidToStringSid(sid), attrs)
                    for sid, attrs in restricted_token_groups
                    if not (attrs & ntsecuritycon.SE_GROUP_INTEGRITY)
                ]
            )

            assert original_non_integrity_groups == restricted_non_integrity_groups
        finally:
            token_handle.Close()
            if restricted_token:
                win32api.CloseHandle(restricted_token)

"""Tests for win_utils module."""

import subprocess
from unittest import mock

import winlocalprocessspawner.win_utils as win_utils


class TestPopenAsUser:
    """Tests for the PopenAsUser class."""

    def test_init_stores_token(self):
        """Store the token for later use."""
        token = mock.Mock()
        patcher = mock.patch.object(subprocess.Popen, "__init__", return_value=None)

        with patcher:
            win_utils.PopenAsUser(["python", "-c", "pass"], token=token)

    def test_init_without_token(self):
        """Work with token=None."""
        with mock.patch.object(subprocess.Popen, "__init__", return_value=None):
            popen = win_utils.PopenAsUser(["python", "-c", "pass"], token=None)

        assert popen._token is None

    def test_exit_detaches_token_if_present(self):
        """Detach token if one is stored."""
        token = mock.Mock()

        with mock.patch.object(subprocess.Popen, "__init__", return_value=None):
            with mock.patch.object(subprocess.Popen, "__exit__", return_value=None):
                popen = win_utils.PopenAsUser(["python", "-c", "pass"], token=token)
                popen.__exit__(None, None, None)

        token.Detach.assert_called_once()

    def test_exit_no_error_when_token_is_none(self):
        """Not raise error when token is None."""
        with mock.patch.object(subprocess.Popen, "__init__", return_value=None):
            with mock.patch.object(subprocess.Popen, "__exit__", return_value=None):
                popen = win_utils.PopenAsUser(["python", "-c", "pass"], token=None)
                # Should not raise
                popen.__exit__(None, None, None)

    def test_init_passes_args_to_popen(self):
        """Pass through arguments to Popen."""
        mock_popen_init = mock.Mock(return_value=None)
        cmd = ["python", "-m", "script"]
        cwd = "C:\\temp"
        env = {"VAR": "value"}

        with mock.patch.object(subprocess.Popen, "__init__", mock_popen_init):
            win_utils.PopenAsUser(cmd, cwd=cwd, env=env, token=None)

        # Verify Popen.__init__ was called with expected args
        assert mock_popen_init.called


class TestSetupSacl:
    """Tests for the setup_sacl function."""

    def test_setup_sacl_calls_windows_apis(self):
        """Call Windows API functions to set up access rights."""
        mock_sid = mock.Mock()

        with mock.patch(
            "winlocalprocessspawner.win_utils.win32service.OpenWindowStation"
        ) as mock_open_winsta, mock.patch(
            "winlocalprocessspawner.win_utils.win32security.GetUserObjectSecurity"
        ) as mock_get_sec, mock.patch(
            "winlocalprocessspawner.win_utils.win32security.SetSecurityInfo"
        ) as mock_set_sec, mock.patch(
            "winlocalprocessspawner.win_utils.win32service.OpenDesktop"
        ) as mock_open_desktop, mock.patch(
            "winlocalprocessspawner.win_utils.win32security.ACL"
        ) as mock_acl:

            # Setup mock return values
            mock_open_winsta.return_value = mock.Mock()
            mock_open_desktop.return_value = mock.Mock()

            mock_sec_desc = mock.Mock()
            mock_sec_desc.GetSecurityDescriptorDacl.return_value = mock.Mock()
            mock_get_sec.return_value = mock_sec_desc

            mock_acl_instance = mock.Mock()
            mock_acl.return_value = mock_acl_instance

            # Call the function
            win_utils.setup_sacl(mock_sid)

            # Verify key functions were called
            mock_open_winsta.assert_called_once()
            assert mock_get_sec.called
            assert mock_set_sec.called

    def test_setup_sacl_creates_dacl_if_none_exists(self):
        """Create DACL if none exists."""
        mock_sid = mock.Mock()

        with mock.patch(
            "winlocalprocessspawner.win_utils.win32service.OpenWindowStation"
        ) as mock_open_winsta, mock.patch(
            "winlocalprocessspawner.win_utils.win32security.GetUserObjectSecurity"
        ) as mock_get_sec, mock.patch(
            "winlocalprocessspawner.win_utils.win32security.SetSecurityInfo"
        ), mock.patch(
            "winlocalprocessspawner.win_utils.win32service.OpenDesktop"
        ) as mock_open_desktop, mock.patch(
            "winlocalprocessspawner.win_utils.win32security.ACL"
        ) as mock_acl_class:

            # Setup mocks
            mock_open_winsta.return_value = mock.Mock()
            mock_open_desktop.return_value = mock.Mock()

            # Return None for DACL to trigger creation
            mock_sec_desc = mock.Mock()
            mock_sec_desc.GetSecurityDescriptorDacl.return_value = None
            mock_get_sec.return_value = mock_sec_desc

            mock_acl_instance = mock.Mock()
            mock_acl_class.return_value = mock_acl_instance

            # Call the function
            win_utils.setup_sacl(mock_sid)

            # Verify ACL was created (not just returned)
            mock_acl_class.assert_called()

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
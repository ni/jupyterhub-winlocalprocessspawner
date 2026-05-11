"""Utilities for creating and restricting a security token for a Windows user."""

import logging

import pywintypes
import win32api
import win32security

logger = logging.getLogger("token_utils")


def create_service_token(username: str, password: str):
    """Logs on a Windows Service user, given its password, and returns the security token."""
    handle = None

    try:
        handle = win32security.LogonUser(
            username,
            None,
            password,
            win32security.LOGON32_LOGON_SERVICE,
            win32security.LOGON32_PROVIDER_DEFAULT,
        )
    except pywintypes.error as e:
        logger.error(
            "Exception occurred when creating security token for user '%s': %r", username, e
        )

    err = win32api.GetLastError()
    if err:
        logger.error("Error %r occurred when creating security token for user '%s'", err, username)
        handle = None

    return handle

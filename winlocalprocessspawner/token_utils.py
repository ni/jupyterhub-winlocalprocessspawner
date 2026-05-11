"""Utilities for creating and restricting a security token for a Windows user."""

import logging

import pywintypes
import win32api
import win32security

logger = logging.getLogger("token_utils")


def create_service_token(username: str, password: str) -> pywintypes.HANDLEType:
    """Logs on a Windows Service user, given its password, and returns a handle to the token."""
    token_handle = None

    try:
        token_handle = win32security.LogonUser(
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
        token_handle = None

    return token_handle


def remove_all_token_privileges(token_handle: pywintypes.HANDLEType) -> int:
    """Disables all privileges in the token, except for SeChangeNotifyPrivilege.

    Returns a new token, with restricted privileges.
    """
    restricted_token = None

    try:
        restricted_token = win32security.CreateRestrictedToken(
            token_handle, win32security.DISABLE_MAX_PRIVILEGE, None, None, None
        )
    except pywintypes.error as e:
        logger.error("Exception occurred when removing privileges from security token: %r", e)

    err = win32api.GetLastError()
    if err:
        logger.error("Error %r occurred when removing privileges from security token", err)
        restricted_token = None

    return restricted_token

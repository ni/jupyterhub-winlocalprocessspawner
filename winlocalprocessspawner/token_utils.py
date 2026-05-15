"""Utilities for creating and restricting a security token for a Windows user."""

import ntsecuritycon
import pywintypes
import win32api
import win32security


def create_service_token(username: str, password: str) -> pywintypes.HANDLEType:
    """Logs on a Windows Service user, given its password, and returns a handle to the token."""
    token_handle = win32security.LogonUser(
        username,
        None,
        password,
        win32security.LOGON32_LOGON_SERVICE,
        win32security.LOGON32_PROVIDER_DEFAULT,
    )

    return token_handle


def restrict_token(token_handle: pywintypes.HANDLEType) -> pywintypes.HANDLEType:
    """Removes token privileges (except SeChangeNotifyPrivilege) and sets medium integrity level.

    Returns a new token, with restricted privileges, and medium integrity level.
    """
    restricted_token = None
    try:
        # Remove privileges
        restricted_token = win32security.CreateRestrictedToken(
            token_handle,
            win32security.DISABLE_MAX_PRIVILEGE,
            None,
            None,
            None,
        )

        # Set Medium integrity level
        medium_integrity_sid = win32security.CreateWellKnownSid(
            win32security.WinMediumLabelSid, None
        )
        win32security.SetTokenInformation(
            restricted_token,
            win32security.TokenIntegrityLevel,
            (medium_integrity_sid, ntsecuritycon.SE_GROUP_INTEGRITY),
        )
    except pywintypes.error:
        if restricted_token:
            win32api.CloseHandle(restricted_token)
        raise

    return restricted_token

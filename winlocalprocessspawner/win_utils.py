import os
import ctypes
import logging
from subprocess import Popen, list2cmdline, Handle

import win32process, win32security, win32service, win32con, win32api, win32event


logger = logging.getLogger('winlocalprocessspawner')


DWORD = ctypes.c_uint
HANDLE = DWORD
BOOL = ctypes.wintypes.BOOL

CLOSEHANDLE = ctypes.windll.kernel32.CloseHandle
CLOSEHANDLE.argtypes = [HANDLE]
CLOSEHANDLE.restype = BOOL

GENERIC_ACCESS = win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.GENERIC_EXECUTE | \
    win32con.GENERIC_ALL

WINSTA_ALL = (win32con.WINSTA_ACCESSCLIPBOARD | win32con.WINSTA_ACCESSGLOBALATOMS |
    win32con.WINSTA_CREATEDESKTOP | win32con.WINSTA_ENUMDESKTOPS  |
    win32con.WINSTA_ENUMERATE  | win32con.WINSTA_EXITWINDOWS  |
    win32con.WINSTA_READATTRIBUTES | win32con.WINSTA_READSCREEN  |
    win32con.WINSTA_WRITEATTRIBUTES | win32con.DELETE     |
    win32con.READ_CONTROL   | win32con.WRITE_DAC    |
    win32con.WRITE_OWNER)


DESKTOP_ALL = (win32con.DESKTOP_CREATEMENU  | win32con.DESKTOP_CREATEWINDOW |
    win32con.DESKTOP_ENUMERATE  | win32con.DESKTOP_HOOKCONTROL |
    win32con.DESKTOP_JOURNALPLAYBACK | win32con.DESKTOP_JOURNALRECORD |
    win32con.DESKTOP_READOBJECTS  | win32con.DESKTOP_SWITCHDESKTOP |
    win32con.DESKTOP_WRITEOBJECTS | win32con.DELETE    |
    win32con.READ_CONTROL   | win32con.WRITE_DAC    |
    win32con.WRITE_OWNER)


def setup_sacl(userGroupSid):
    """ Without this setup, the single user server will likely fail with either Error 0x0000142 or
    ExitCode -1073741502. This sets up access for the given user to the WinSta (Window Station)
    and Desktop objects.
    """

    # Set access rights to window station
    hWinSta = win32service.OpenWindowStation("winsta0", False, win32con.READ_CONTROL | \
                                        win32con.WRITE_DAC)
    # Get security descriptor by winsta0-handle
    secDescWinSta = win32security.GetUserObjectSecurity(hWinSta,
                   win32security.OWNER_SECURITY_INFORMATION
                   | win32security.DACL_SECURITY_INFORMATION
                   | win32con.GROUP_SECURITY_INFORMATION)
    # Get DACL from security descriptor
    daclWinSta = secDescWinSta.GetSecurityDescriptorDacl()
    if daclWinSta is None:
     # Create DACL if not exisiting
     daclWinSta = win32security.ACL()
    # Add ACEs to DACL for specific user group
    daclWinSta.AddAccessAllowedAce(win32security.ACL_REVISION_DS, GENERIC_ACCESS, userGroupSid)
    daclWinSta.AddAccessAllowedAce(win32security.ACL_REVISION_DS, WINSTA_ALL, userGroupSid)
    # Set modified DACL for winsta0
    win32security.SetSecurityInfo(hWinSta, win32security.SE_WINDOW_OBJECT,
            win32security.DACL_SECURITY_INFORMATION, None, None, daclWinSta, None)

    # Set access rights to desktop
    hDesktop = win32service.OpenDesktop("default", 0, False, win32con.READ_CONTROL
                  | win32con.WRITE_DAC
                  | win32con.DESKTOP_WRITEOBJECTS
                  | win32con.DESKTOP_READOBJECTS)
    # Get security descriptor by desktop-handle
    secDescDesktop = win32security.GetUserObjectSecurity(hDesktop,
                    win32security.OWNER_SECURITY_INFORMATION
                    | win32security.DACL_SECURITY_INFORMATION
                    | win32con.GROUP_SECURITY_INFORMATION)
    # Get DACL from security descriptor
    daclDesktop = secDescDesktop.GetSecurityDescriptorDacl()
    if daclDesktop is None:
     #create DACL if not exisiting
     daclDesktop = win32security.ACL()
    # Add ACEs to DACL for specific user group
    daclDesktop.AddAccessAllowedAce(win32security.ACL_REVISION_DS, GENERIC_ACCESS, userGroupSid)
    daclDesktop.AddAccessAllowedAce(win32security.ACL_REVISION_DS, DESKTOP_ALL, userGroupSid)
    # Set modified DACL for desktop
    win32security.SetSecurityInfo(hDesktop, win32security.SE_WINDOW_OBJECT,
            win32security.DACL_SECURITY_INFORMATION, None, None, daclDesktop, None)


class PopenAsUser(Popen):
    """
    Popen implementation that launches new process using the windows auth token provided.
    This is needed to be able to launch a process as another user.
    """

    def __init__(self, args, bufsize=-1, executable=None,
                 stdin=None, stdout=None, stderr=None,
                 shell=False, cwd=None, env=None, universal_newlines=False,
                 startupinfo=None, creationflags=0, *, encoding=None,
                 errors=None, token=None):
        """Create new PopenAsUser instance."""
        self._token = token

        super().__init__(args, bufsize, executable,
                         stdin, stdout, stderr, None, False,
                         shell, cwd, env, universal_newlines,
                         startupinfo, creationflags, False, False, (),
                         encoding=encoding, errors=errors)

    def __exit__(self, type, value, traceback):
        # Detach to avoid invalidating underlying winhandle
        self._token.Detach()
        super().__exit__(type, value, traceback)

    # Mainly adapted from subprocess._execute_child, with the main exception that this
    # function calls CreateProcessAsUser instead of CreateProcess
    def _execute_child(self, args, executable, preexec_fn, close_fds,
                       pass_fds, cwd, env,
                       startupinfo, creationflags, shell,
                       p2cread, p2cwrite,
                       c2pread, c2pwrite,
                       errread, errwrite,
                       unused_restore_signals, unused_start_new_session):
        """Execute program"""

        assert not pass_fds, "pass_fds not supported on Windows."

        if not isinstance(args, str):
            args = list2cmdline(args)

        # Process startup details
        if startupinfo is None:
            startupinfo = win32process.STARTUPINFO()
        if -1 not in (p2cread, c2pwrite, errwrite):
            startupinfo.dwFlags |= win32process.STARTF_USESTDHANDLES
            startupinfo.hStdInput = p2cread
            startupinfo.hStdOutput = c2pwrite
            startupinfo.hStdError = errwrite

        if shell:
            startupinfo.dwFlags |= win32process.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = win32process.SW_HIDE
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            args = '{} /c "{}"'.format(comspec, args)

        sid, _ = win32security.GetTokenInformation(self._token, win32security.TokenUser)
        setup_sacl(sid)

        # Start the process
        try:
            hp, ht, pid, tid = win32process.CreateProcessAsUser(self._token, executable, args,
                                                        # no special security
                                                        None, None,
                                                        int(not close_fds),
                                                        creationflags,
                                                        env,
                                                        os.fspath(cwd) if cwd is not None else None,
                                                        startupinfo)
            err = win32api.GetLastError()
            if err:
                logger.error("Error %r when calling CreateProcessAsUser executable %s args %s with the \
                            token %r ", err, executable, args, self._token)
            else:
                win32event.WaitForSingleObject(hp, 1000)  # Wait at least one second before checking exit code
                logger.error("ExitCode %r when calling CreateProcessAsUser executable %s args %s with the \
                            token %r ", win32process.GetExitCodeProcess(hp), executable, args, self._token)
        finally:
            # Child is launched. Close the parent's copy of those pipe
            # handles that only the child should have open.  You need
            # to make sure that no handles to the write end of the
            # output pipe are maintained in this process or else the
            # pipe will not close when the child process exits and the
            # ReadFile will hang.
            if p2cread != -1:
                p2cread.Close()
            if c2pwrite != -1:
                c2pwrite.Close()
            if errwrite != -1:
                errwrite.Close()
            if hasattr(self, '_devnull'):
                os.close(self._devnull)

        try:
            # Retain the process handle, but close the thread handle
            self._child_created = True
            # Popen stores the win handle as an int, not as a PyHandle
            self._handle = Handle(hp.Detach())
            self.pid = pid
        finally:
            CLOSEHANDLE(ht)

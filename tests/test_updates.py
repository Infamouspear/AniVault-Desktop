from urllib.error import URLError
import pytest
from anime_hub import updates

REPO = "Example/AniVault-Desktop"
INDEX = "https://github.com/" + REPO + "/releases"
TAG = "v1.2.0"
NAME = "AniVault-1.2.0-Setup.exe"

@pytest.fixture
def release():
    return {"tag_name": TAG, "draft": False, "prerelease": False,
            "html_url": INDEX + "/tag/" + TAG, "body": "Poster library",
            "assets": [{"name": NAME, "state": "uploaded", "digest": "sha256:" + "a"*64,
                        "browser_download_url": INDEX + "/download/" + TAG + "/" + NAME}]}

def test_stable_supersedes_rc_but_not_newer_release(release):
    assert updates.parse_release(release, REPO, "1.2.0-rc.1") == (TAG, INDEX+"/tag/"+TAG, "Poster library", "a"*64)
    assert updates.parse_release(release, REPO, "1.2.0") is None
    assert updates.parse_release(release, REPO, "1.10.0") is None

@pytest.mark.parametrize("field,value", [
    ("html_url", "https://example.com/setup"), ("draft", True),
    ("prerelease", True), ("assets", []), ("tag_name", "../latest"),
])
def test_target_and_release_validation(release, field, value):
    release[field] = value
    with pytest.raises(ValueError):
        updates.parse_release(release, REPO, "1.1.2")

@pytest.mark.parametrize("field,value", [("digest", None), ("state", "new"), ("browser_download_url", "https://example.com/setup.exe")])
def test_asset_validation(release, field, value):
    release["assets"][0][field] = value
    with pytest.raises(ValueError):
        updates.parse_release(release, REPO, "1.1.2")

def test_offline_check_does_not_retry_or_redirect(monkeypatch):
    class Offline:
        def open(self, request, timeout):
            assert request.full_url == "https://api.github.com/repos/" + REPO + "/releases/latest"
            assert not request.has_header("Authorization")
            raise URLError("offline")
    monkeypatch.setattr(updates, "build_opener", lambda handler: Offline())
    with pytest.raises(URLError):
        updates.check_release(REPO, "1.1.2")

@pytest.mark.parametrize("corrupt", [False, True])
def test_download_verifies_bytes_and_cleans_up(monkeypatch, tmp_path, release, corrupt):
    import hashlib
    import io
    import tempfile
    repo = updates.RELEASE_REPOSITORY
    target = f"https://github.com/{repo}/releases/tag/{TAG}"
    payload = b"test installer bytes"
    digest = hashlib.sha256(payload).hexdigest()
    folder = tmp_path / "download"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(folder))
    class FixtureOpener:
        def open(self, url, timeout):
            assert url == f"https://github.com/{repo}/releases/download/{TAG}/{NAME}"
            return io.BytesIO(payload if not corrupt else payload + b"changed")
    monkeypatch.setattr(updates, "build_opener", lambda _: FixtureOpener())
    args = (TAG, target, "", digest)
    if corrupt:
        with pytest.raises(ValueError, match="checksum"):
            updates.download_installer(args)
        assert not folder.exists()
    else:
        assert updates.download_installer(args).read_bytes() == payload

@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows update handoff")
def test_update_recovers_only_old_hidden_matching_instances(monkeypatch, tmp_path):
    import base64
    import hashlib
    import subprocess
    import sys

    installed = tmp_path / "installed" / "AniVault.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"fixture app")
    installer = tmp_path / "download" / "setup.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"fixture installer")
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(sys, "frozen", True, raising=False)
        patch.setattr(sys, "executable", str(installed))
        patch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
        patch.setattr(subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))
        updates.launch_installer_after_exit(installer, hashlib.sha256(installer.read_bytes()).hexdigest())
    args, options = calls[0]
    original = base64.b64decode(args[-1]).decode("utf-16le")
    original = original.replace(
        "Add-Type -AssemblyName System.Windows.Forms",
        "throw $message",
    )
    # Exercise the real PowerShell control flow with process/installer fixtures.
    # No real application is closed or executed by this test.
    fixture = r"""
$script:attempts = 0
$script:stopped = @()
$script:restarted = $false
function Get-Process {
    [CmdletBinding()]
    param([int]$Id, [string]$Name)
    if ($PSBoundParameters.ContainsKey('Id')) { return }
    $old = [pscustomobject]@{
        Id=12345; Path=$env:ANIVAULT_UPDATE_APP; MainWindowHandle=0;
        StartTime=(Get-Date).AddHours(-3)
    }
    $old | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($timeout) return $true }
    $old
    [pscustomobject]@{
        Id=12346; Path=$env:ANIVAULT_UPDATE_APP; MainWindowHandle=1;
        StartTime=(Get-Date).AddHours(-3)
    }
    [pscustomobject]@{
        Id=12347; Path='C:\another-install\AniVault.exe'; MainWindowHandle=0;
        StartTime=(Get-Date).AddHours(-3)
    }
}
function Stop-Process {
    [CmdletBinding()]
    param([int]$Id, [switch]$Force)
    $script:stopped += $Id
}
function Start-Process {
    [CmdletBinding()]
    param([string]$FilePath, [string[]]$ArgumentList, [string]$WindowStyle,
          [string]$WorkingDirectory, [switch]$Wait, [switch]$PassThru)
    if ($FilePath -eq $env:ANIVAULT_UPDATE_FILE) {
        $script:attempts++
        if (-not ($ArgumentList -contains '/CLOSEAPPLICATIONS')) { throw 'Graceful close missing' }
        if (-not ($ArgumentList | Where-Object { $_ -like '/LOG=*' })) { throw 'Log missing' }
        [pscustomobject]@{ExitCode= $(if ($script:attempts -eq 1) {5} else {0})}
    } else {
        $script:restarted = $FilePath -eq $env:ANIVAULT_UPDATE_APP -and $env:PYINSTALLER_RESET_ENVIRONMENT -eq '1'
    }
}
"""
    assertions = r"""
if ($script:attempts -ne 2) {throw 'Expected one recovery retry'}
if ($script:stopped.Count -ne 1 -or $script:stopped[0] -ne 12345) {throw 'Unsafe process selection'}
if (-not $script:restarted) {throw 'Application was not restarted'}
"""
    script = base64.b64encode((fixture + original + assertions).encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [args[0], "-NoProfile", "-NonInteractive", "-EncodedCommand", script],
        env=options["env"], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not installer.exists()

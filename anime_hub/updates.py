"""Stable-release discovery and verified, user-initiated installation."""
import json
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

RELEASE_REPOSITORY = "Infamouspear/AniVault-Desktop"
_VERSION = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.([1-9][0-9]*))?")
_REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")


def version_key(value):
    if not isinstance(value, str) or len(value) > 60:
        raise ValueError("Unsupported release version")
    match = _VERSION.fullmatch(value)
    if not match:
        raise ValueError("Unsupported release version")
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), rc is None, int(rc or 0)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def release_index(repository):
    if not _REPOSITORY.fullmatch(repository) or repository.split("/")[1] in {".", ".."}:
        raise ValueError("Desktop release repository is not configured")
    return f"https://github.com/{repository}/releases"


def parse_release(payload, repository, current):
    index = release_index(repository)
    if not isinstance(payload, dict) or payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise ValueError("Expected a published stable release")
    tag = payload.get("tag_name")
    version = version_key(tag)
    if not version[3] or payload.get("html_url") != f"{index}/tag/{tag}":
        raise ValueError("Release does not match the configured repository")
    if version <= version_key(current):
        return None
    filename = f"AniVault-{tag.removeprefix('v')}-Setup.exe"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Release assets are missing")
    installers = [a for a in assets if isinstance(a, dict) and a.get("name") == filename]
    if len(installers) != 1:
        raise ValueError("Release installer is missing or ambiguous")
    asset = installers[0]
    digest = asset.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Release installer has no valid SHA-256 digest")
    if asset.get("state") != "uploaded" or asset.get("browser_download_url") != f"{index}/download/{tag}/{filename}":
        raise ValueError("Release installer does not match the configured repository")
    body = payload.get("body")
    return tag, payload["html_url"], body[:4000] if isinstance(body, str) else "", digest[7:]


def check_release(repository, current):
    release_index(repository)
    request = Request(f"https://api.github.com/repos/{repository}/releases/latest",
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "AniVault-Desktop"})
    with build_opener(NoRedirect()).open(request, timeout=8) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Release metadata exceeded its size limit")
    return parse_release(json.loads(raw), repository, current)

class AssetRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        url = urlsplit(newurl)
        if (url.scheme != "https" or url.netloc not in
                {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}):
            raise ValueError("GitHub redirected the installer to an unexpected address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_installer(release):
    import hashlib
    import shutil
    import tempfile
    import time
    from pathlib import Path

    tag, url, _, expected = release
    index = release_index(RELEASE_REPOSITORY)
    if not version_key(tag)[3] or url != f"{index}/tag/{tag}" or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid installer release")
    filename = f"AniVault-{tag.removeprefix('v')}-Setup.exe"
    folder = Path(tempfile.mkdtemp(prefix="AniVault-update-")).resolve()
    path = folder / filename
    digest = hashlib.sha256()
    size = 0
    deadline = time.monotonic() + 600
    try:
        with build_opener(AssetRedirect()).open(f"{index}/download/{tag}/{filename}", timeout=20) as response, path.open("xb") as output:
            while chunk := response.read(256 * 1024):
                size += len(chunk)
                if size > 512 * 1024 * 1024 or time.monotonic() > deadline:
                    raise ValueError("Installer download exceeded its limits")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("Installer checksum did not match GitHub")
        return path
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def launch_installer_after_exit(path, expected):
    import base64
    import os
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise ValueError("In-app installation requires the installed Windows build")
    script = r"""
$ErrorActionPreference = 'Stop'
$restart = $false
try {
    $old = Get-Process -Id ([int]$env:ANIVAULT_UPDATE_PID) -ErrorAction SilentlyContinue
    if ($null -ne $old -and -not $old.WaitForExit(120000)) { throw 'AniVault did not close in time.' }
    $restart = $true
    if ((Get-FileHash -LiteralPath $env:ANIVAULT_UPDATE_FILE -Algorithm SHA256).Hash -ne $env:ANIVAULT_UPDATE_HASH) {
        throw 'Installer checksum changed.'
    }
    $dir = Split-Path -Parent $env:ANIVAULT_UPDATE_APP
    $setup = Start-Process -FilePath $env:ANIVAULT_UPDATE_FILE -ArgumentList @(
        '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOCLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS',
        ('/DIR="' + $dir + '"')) -Wait -PassThru
    if ($setup.ExitCode -ne 0) { throw ('Installer exit code: ' + $setup.ExitCode) }
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'AniVault update failed')
} finally {
    Remove-Item -LiteralPath $env:ANIVAULT_UPDATE_FILE -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Split-Path -Parent $env:ANIVAULT_UPDATE_FILE) -ErrorAction SilentlyContinue
    if ($restart -and (Test-Path -LiteralPath $env:ANIVAULT_UPDATE_APP)) {
        $env:PYINSTALLER_RESET_ENVIRONMENT = "1"
        Start-Process -FilePath $env:ANIVAULT_UPDATE_APP -WorkingDirectory (Split-Path -Parent $env:ANIVAULT_UPDATE_APP)
    }
}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    env = dict(os.environ, ANIVAULT_UPDATE_PID=str(os.getpid()),
               ANIVAULT_UPDATE_APP=sys.executable, ANIVAULT_UPDATE_FILE=str(path),
               ANIVAULT_UPDATE_HASH=expected)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                     env=env, creationflags=subprocess.CREATE_NO_WINDOW)

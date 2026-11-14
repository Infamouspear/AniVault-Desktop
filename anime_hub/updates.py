"""Read-only stable-release discovery. Installation stays with the user."""
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

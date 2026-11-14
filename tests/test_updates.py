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

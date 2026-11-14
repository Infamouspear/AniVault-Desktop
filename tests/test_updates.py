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

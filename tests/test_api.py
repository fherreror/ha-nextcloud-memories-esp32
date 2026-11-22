"""Offline tests for the Nextcloud Memories HTTP client."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp
import pytest

API_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "nextcloud_memories"
    / "api.py"
)
# Import the lightweight client without importing the Home Assistant integration package.
spec = importlib.util.spec_from_file_location("nextcloud_memories_api_under_test", API_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NextcloudMemoriesClient = module.NextcloudMemoriesClient


@pytest.fixture
def client():
    """Return a client that cannot reach a real server."""
    return NextcloudMemoriesClient(
        session=None,
        base_url="http://nextcloud.invalid/",
        api_token="dummy-test-token",
        username="tester",
    )


def test_url_and_basic_auth(client):
    assert client._build_url("/apps/memories") == "http://nextcloud.invalid/apps/memories"
    assert client._build_url("apps/memories") == "http://nextcloud.invalid/apps/memories"
    assert client._basic_auth == aiohttp.BasicAuth("tester", "dummy-test-token")
    assert "Authorization" not in client._json_headers()


def test_legacy_token_headers():
    client = NextcloudMemoriesClient(
        session=None, base_url="http://nextcloud.invalid", api_token="dummy-test-token"
    )
    assert client._json_headers()["Authorization"] == "Bearer dummy-test-token"
    assert client._bytes_headers()["Authorization"] == "Bearer dummy-test-token"


def test_extract_albums_deduplicates_and_filters(client):
    payload = [
        {"cluster_id": "tester/Family", "name": "Family", "id": 12},
        {"cluster_id": "tester/Family", "name": "Duplicate"},
        {"id": 34, "title": "Travel"},
        {"name": "No ID"},
        "not a dict",
    ]
    albums = client._extract_albums(payload)
    assert [(a["id"], a["name"]) for a in albums] == [
        ("tester/Family", "Family"), ("34", "Travel")
    ]


def test_extract_nested_albums(client):
    payload = {"response": {"items": [{"path": "tester/Trips", "title": "Trips"}]}}
    albums = client._extract_albums(payload)
    assert [(a["id"], a["name"]) for a in albums] == [("tester/Trips", "Trips")]


def test_append_photo_ignores_duplicate_and_non_image(client):
    photos = []
    seen = set()
    client._append_photo(
        photos, seen, {"fileid": 7, "basename": "one.jpg", "mimetype": "image/jpeg"}
    )
    client._append_photo(photos, seen, {"fileid": 7, "mimetype": "image/png"})
    client._append_photo(photos, seen, {"fileid": 8, "mimetype": "video/mp4"})
    client._append_photo(photos, seen, {"fileid": "9", "mimetype": "image/jpeg"})
    assert [p["fileid"] for p in photos] == [7]
    assert photos[0]["name"] == "one.jpg"


def test_resolve_numeric_album_to_cluster_path(client):
    client._request_json_candidates = AsyncMock(
        return_value=[{"id": 44, "cluster_id": "tester/Trips", "name": "Trips"}]
    )
    assert asyncio.run(client._resolve_album_reference("44")) == "tester/Trips"


def test_get_photo_list_without_network_and_private_token(client):
    client._request_json_candidates = AsyncMock(
        return_value=[
            {"detail": [
                {"fileid": 10, "mimetype": "image/jpeg"},
                {"fileid": 11, "mimetype": "image/png"},
                {"fileid": 12, "mimetype": "video/mp4"},
            ]}
        ]
    )
    photos = asyncio.run(
        client.async_get_photo_list("tester/Trips", max_photos=1, randomize=False)
    )
    assert [p["fileid"] for p in photos] == [10]
    params = client._request_json_candidates.await_args.kwargs["params_candidates"]
    assert all("token" not in p for p in params)


def test_photo_preview_parameters_without_network(client):
    client._request_bytes_candidates = AsyncMock(return_value=b"fake-jpeg")
    result = asyncio.run(
        client.async_get_photo_preview(
            fileid=101, width=800, height=480, album_id="tester/Trips", etag="v1"
        )
    )
    assert result == b"fake-jpeg"
    call = client._request_bytes_candidates.await_args
    assert call.kwargs["params_candidates"][0] == {
        "x": 800, "y": 480, "a": 1, "c": "v1"
    }

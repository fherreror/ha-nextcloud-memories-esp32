"""Async client for Nextcloud Memories."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import json
import random
import re
from typing import Any

import aiohttp


class NextcloudMemoriesClient:
    """Small API client around Nextcloud Memories endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_token: str,
        verify_ssl: bool = True,
        username: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token.strip()
        self._username = (username or "").strip() or None
        self._verify_ssl = verify_ssl

        # Compatibility mode for old config entries without username.
        self._legacy_bearer_mode = self._username is None
        self._basic_auth = (
            aiohttp.BasicAuth(self._username, self._api_token)
            if self._username is not None
            else None
        )

        self._requesttoken: str | None = None
        self._auth_lock = asyncio.Lock()

    def _build_url(self, path: str) -> str:
        if path.startswith("/"):
            return f"{self._base_url}{path}"
        return f"{self._base_url}/{path}"

    def _json_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "OCS-APIRequest": "true",
        }
        if self._legacy_bearer_mode:
            headers["Authorization"] = f"Bearer {self._api_token}"
        elif self._requesttoken:
            headers["requesttoken"] = self._requesttoken
        return headers

    def _bytes_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "OCS-APIRequest": "true",
        }
        if self._legacy_bearer_mode:
            headers["Authorization"] = f"Bearer {self._api_token}"
        elif self._requesttoken:
            headers["requesttoken"] = self._requesttoken
        return headers

    async def async_test_connection(self) -> None:
        """Validate connectivity/authentication."""
        await self._request_json_candidates(
            paths=(
                "/apps/memories/api/describe",
                "/index.php/apps/memories/api/describe",
            ),
            params_candidates=(None,),
        )

    async def async_get_albums(self) -> list[dict[str, Any]]:
        """Return normalized album list."""
        payload = await self._request_json_candidates(
            paths=(
                "/apps/memories/api/clusters/albums",
                "/index.php/apps/memories/api/clusters/albums",
                "/apps/memories/api/albums",
                "/index.php/apps/memories/api/albums",
            ),
            params_candidates=(None,),
        )
        return self._extract_albums(payload)

    async def async_get_photo_list(
        self, album_id: str, max_photos: int, randomize: bool
    ) -> list[dict[str, Any]]:
        """Return normalized photo metadata from one album."""
        album_ref = await self._resolve_album_reference(album_id)
        days_params = {
            "albums": album_ref,
            "monthView": 1,
            "reverse": 1,
        }
        params_candidates: list[dict[str, Any]] = [days_params]
        # Public-link token mode only; private albums should not send token=<album_id>.
        if "/" not in album_ref and len(album_ref) >= 12:
            params_candidates.append({**days_params, "token": album_ref})

        days_payload = await self._request_json_candidates(
            paths=(
                "/apps/memories/api/days",
                "/index.php/apps/memories/api/days",
            ),
            params_candidates=params_candidates,
        )

        photos = await self._extract_photos_from_days(days_payload, album_ref)
        if randomize:
            random.shuffle(photos)
        if max_photos > 0:
            photos = photos[:max_photos]
        return photos

    async def async_get_photo_preview(
        self,
        fileid: int,
        width: int,
        height: int,
        album_id: str | None,
        etag: str | None = None,
    ) -> bytes:
        """Download one Memories preview."""
        params: dict[str, Any] = {
            "x": width,
            "y": height,
            "a": 1,
        }
        if etag:
            params["c"] = etag

        params_candidates: list[dict[str, Any]] = [params]
        if album_id and self._legacy_bearer_mode:
            params_candidates.append({**params, "albums": album_id, "token": album_id})

        try:
            return await self._request_bytes_candidates(
                paths=(
                    f"/apps/memories/api/image/preview/{fileid}",
                    f"/index.php/apps/memories/api/image/preview/{fileid}",
                ),
                params_candidates=params_candidates,
            )
        except aiohttp.ClientResponseError:
            # Some instances reject c=etag. Retry without it.
            if "c" in params:
                params.pop("c", None)
                return await self._request_bytes_candidates(
                    paths=(
                        f"/apps/memories/api/image/preview/{fileid}",
                        f"/index.php/apps/memories/api/image/preview/{fileid}",
                    ),
                    params_candidates=[params],
                )
            raise

    async def _ensure_authenticated(self) -> None:
        if self._legacy_bearer_mode:
            return

        if self._requesttoken:
            return

        async with self._auth_lock:
            if self._requesttoken:
                return

            await self._login_with_session()
            await self._refresh_requesttoken()

    async def _login_with_session(self) -> None:
        login_html = await self._fetch_text_candidates(
            paths=("/login", "/index.php/login")
        )
        token_match = re.search(r'name="requesttoken"\s+value="([^"]+)"', login_html)
        if not token_match:
            token_match = re.search(r'data-requesttoken="([^"]+)"', login_html)
        if not token_match:
            token_match = re.search(r'"requesttoken":"([^"]+)"', login_html)
        if not token_match:
            raise RuntimeError("Could not extract login requesttoken from Nextcloud login page")

        login_token = token_match.group(1)
        post_data = {
            "user": self._username,
            "userlogin": self._username,
            "password": self._api_token,
            "requesttoken": login_token,
        }

        for path in ("/login", "/index.php/login"):
            url = self._build_url(path)
            async with self._session.post(
                url,
                data=post_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                ssl=self._verify_ssl,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as response:
                if response.status in (401, 403):
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=response.status,
                        message="Invalid credentials",
                        headers=response.headers,
                    )
                if response.status < 500:
                    return

        raise RuntimeError("Could not create Nextcloud session")

    async def _refresh_requesttoken(self) -> None:
        html = await self._fetch_text_candidates(
            paths=(
                "/apps/memories/",
                "/index.php/apps/memories/",
            )
        )

        # Preferred source in Memories frontend HTML.
        match = re.search(r'data-requesttoken="([^"]+)"', html)
        if not match:
            match = re.search(r'"requesttoken":"([^"]+)"', html)
        if not match:
            raise RuntimeError("Could not extract requesttoken from Memories page")

        self._requesttoken = match.group(1)

    async def _fetch_text_candidates(self, paths: Iterable[str]) -> str:
        errors: list[Exception] = []
        for path in paths:
            try:
                async with self._session.get(
                    self._build_url(path),
                    ssl=self._verify_ssl,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    return await response.text()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[-1]
        raise RuntimeError("No candidate URL to fetch text")

    async def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._build_url(path)

        async def do_request(auth: aiohttp.BasicAuth | None) -> Any:
            async with self._session.get(
                url,
                params=params,
                headers=self._json_headers(),
                auth=auth,
                ssl=self._verify_ssl,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                body = await response.text()
                if not body.strip():
                    return {}
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Invalid JSON from {url}") from exc

        if self._legacy_bearer_mode:
            return await do_request(None)

        if self._requesttoken:
            return await do_request(None)

        # Prefer BasicAuth with app password when username is configured.
        if self._basic_auth is not None:
            try:
                return await do_request(self._basic_auth)
            except aiohttp.ClientResponseError as exc:
                if exc.status not in (401, 403, 412):
                    raise

        # Fallback: browser-like session + requesttoken.
        await self._ensure_authenticated()
        return await do_request(None)

    async def _request_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        url = self._build_url(path)

        async def do_request(auth: aiohttp.BasicAuth | None) -> bytes:
            async with self._session.get(
                url,
                params=params,
                headers=self._bytes_headers(),
                auth=auth,
                ssl=self._verify_ssl,
                timeout=aiohttp.ClientTimeout(total=45),
            ) as response:
                response.raise_for_status()
                return await response.read()

        if self._legacy_bearer_mode:
            return await do_request(None)

        if self._requesttoken:
            return await do_request(None)

        if self._basic_auth is not None:
            try:
                return await do_request(self._basic_auth)
            except aiohttp.ClientResponseError as exc:
                if exc.status not in (401, 403, 412):
                    raise

        await self._ensure_authenticated()
        return await do_request(None)

    async def _request_json_candidates(
        self,
        paths: Iterable[str],
        params_candidates: Iterable[dict[str, Any] | None],
    ) -> Any:
        errors: list[Exception] = []
        for path in paths:
            for params in params_candidates:
                try:
                    return await self._request_json(path, params=params)
                except aiohttp.ClientResponseError as exc:
                    errors.append(exc)
                    if exc.status in (401, 403):
                        # Session may be stale. Try re-auth once.
                        if not self._legacy_bearer_mode:
                            self._requesttoken = None
                            await self._ensure_authenticated()
                        continue
                except (aiohttp.ClientError, RuntimeError) as exc:
                    errors.append(exc)

        if errors:
            raise errors[-1]
        raise RuntimeError("No candidate endpoint to call")

    async def _request_bytes_candidates(
        self,
        paths: Iterable[str],
        params_candidates: Iterable[dict[str, Any] | None],
    ) -> bytes:
        errors: list[Exception] = []
        for path in paths:
            for params in params_candidates:
                try:
                    return await self._request_bytes(path, params=params)
                except aiohttp.ClientResponseError as exc:
                    errors.append(exc)
                    if exc.status in (401, 403):
                        if not self._legacy_bearer_mode:
                            self._requesttoken = None
                            await self._ensure_authenticated()
                        continue
                except aiohttp.ClientError as exc:
                    errors.append(exc)

        if errors:
            raise errors[-1]
        raise RuntimeError("No candidate endpoint to call")

    def _extract_albums(self, payload: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                album_id = self._first_scalar(
                    item, ("cluster_id", "path", "id", "album_id", "albumid")
                )
                album_name = self._first_scalar(item, ("name", "title", "displayName", "basename", "path"))
                if album_id is None or album_name is None:
                    continue
                norm_id = str(album_id)
                if norm_id in seen:
                    continue
                out.append(
                    {
                        "id": norm_id,
                        "name": str(album_name),
                        "legacy_album_id": item.get("album_id"),
                        "raw": item,
                    }
                )
                seen.add(norm_id)
            return out

        # Generic fallback parser.
        stack: list[Any] = [payload]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                album_id = self._first_scalar(
                    cur, ("cluster_id", "path", "albumid", "album_id", "id", "token")
                )
                album_name = self._first_scalar(cur, ("name", "title", "displayName", "basename", "path"))
                if album_id is not None and album_name is not None:
                    norm_id = str(album_id)
                    if norm_id not in seen:
                        out.append(
                            {
                                "id": norm_id,
                                "name": str(album_name),
                                "legacy_album_id": cur.get("album_id"),
                                "raw": cur,
                            }
                        )
                        seen.add(norm_id)
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)

        return out

    async def _extract_photos_from_days(self, payload: Any, album_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[int] = set()

        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue

                if isinstance(item.get("fileid"), int):
                    self._append_photo(out, seen, item)
                    continue

                dayid = item.get("dayid")
                detail = item.get("detail")

                if isinstance(detail, list) and detail:
                    for photo in detail:
                        if isinstance(photo, dict):
                            self._append_photo(out, seen, photo)
                    continue

                if isinstance(dayid, int) and int(item.get("count", 0)) > 0:
                    day_payload = await self._request_json_candidates(
                        paths=(
                            f"/apps/memories/api/days/{dayid},{dayid}",
                            f"/index.php/apps/memories/api/days/{dayid},{dayid}",
                        ),
                        params_candidates=(
                            {"albums": album_id, "monthView": 1, "reverse": 1},
                            {"albums": album_id, "token": album_id, "monthView": 1, "reverse": 1},
                        ),
                    )
                    if isinstance(day_payload, list):
                        for photo in day_payload:
                            if isinstance(photo, dict):
                                self._append_photo(out, seen, photo)

        return out

    async def _resolve_album_reference(self, album_id: str) -> str:
        """Resolve album identifier accepted by /days.

        For private albums, /days expects the album path (e.g. user/Example Album),
        while UI may expose numeric IDs.
        """
        raw = str(album_id).strip()
        if not raw:
            return raw

        # Already a path-like identifier.
        if "/" in raw:
            return raw

        # Try mapping numeric/id value to album path from clusters/albums payload.
        try:
            payload = await self._request_json_candidates(
                paths=(
                    "/apps/memories/api/clusters/albums",
                    "/index.php/apps/memories/api/clusters/albums",
                    "/apps/memories/api/albums",
                    "/index.php/apps/memories/api/albums",
                ),
                params_candidates=(None,),
            )
            for item in self._iter_dicts(payload):
                item_id = item.get("id")
                item_album_id = item.get("album_id")
                item_albumid = item.get("albumid")
                item_cluster_id = item.get("cluster_id")
                if (
                    str(item_id) == raw
                    or str(item_album_id) == raw
                    or str(item_albumid) == raw
                    or str(item_cluster_id) == raw
                ):
                    cluster_id = item.get("cluster_id")
                    if isinstance(cluster_id, str) and cluster_id.strip():
                        return cluster_id.strip()
                    path = item.get("path")
                    if isinstance(path, str) and path.strip():
                        return path.strip()
                    name = item.get("name")
                    user = item.get("user") or self._username
                    if isinstance(name, str) and name.strip() and isinstance(user, str) and user.strip():
                        return f"{user.strip()}/{name.strip()}"
        except Exception:
            # Fallback to original value.
            pass

        return raw

    def _iter_dicts(self, obj: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        stack: list[Any] = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                out.append(cur)
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        return out

    def _append_photo(self, out: list[dict[str, Any]], seen: set[int], photo: dict[str, Any]) -> None:
        fileid = photo.get("fileid")
        if not isinstance(fileid, int) or fileid in seen:
            return

        mimetype = photo.get("mimetype")
        if isinstance(mimetype, str) and not mimetype.startswith("image/"):
            return

        out.append(
            {
                "fileid": fileid,
                "name": self._first_scalar(photo, ("basename", "name", "filename")),
                "path": self._first_scalar(photo, ("path", "filePath")),
                "date": self._first_scalar(photo, ("dateTaken", "datetaken", "date", "timestamp", "epoch")),
                "etag": self._first_scalar(photo, ("etag",)),
                "mimetype": mimetype,
                "w": photo.get("w"),
                "h": photo.get("h"),
                "raw": photo,
            }
        )
        seen.add(fileid)

    @staticmethod
    def _first_scalar(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = source.get(key)
            if isinstance(value, (str, int, float, bool)):
                return value
        return None

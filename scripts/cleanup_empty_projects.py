#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class ApiError(RuntimeError):
    pass


@dataclass
class ApiClient:
    base_url: str
    auth_token: Optional[str]
    tenant_id: Optional[str]
    timeout_s: float
    insecure_tls: bool = False

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self.tenant_id:
            headers["X-Tenant-Id"] = self.tenant_id
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Any]:
        base = self.base_url.rstrip("/")
        url = f"{base}{path}"
        if query:
            encoded = urllib.parse.urlencode(
                {k: v for k, v in query.items() if v is not None and v != ""},
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"

        body: Optional[bytes] = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url=url,
            method=method,
            headers=self._headers(headers),
            data=body,
        )
        try:
            context: Optional[ssl.SSLContext] = None
            if self.insecure_tls and url.startswith("https://"):
                context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=self.timeout_s, context=context) as resp:
                raw = resp.read()
                if not raw:
                    return resp.status, None
                try:
                    return resp.status, json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    return resp.status, raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return exc.code, parsed
        except urllib.error.URLError as exc:
            raise ApiError(f"request failed: {method} {url}: {exc}") from exc

    def list_projects(self, limit: int = 200) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            status, data = self._request(
                "GET",
                "/projects",
                query={"limit": limit, "cursor": cursor},
            )
            if status != 200 or not isinstance(data, dict):
                raise ApiError(f"GET /projects failed: HTTP {status} body={data!r}")
            page_items = data.get("items")
            if not isinstance(page_items, list):
                raise ApiError(f"GET /projects returned invalid payload: {data!r}")
            items.extend([item for item in page_items if isinstance(item, dict)])
            next_cursor = data.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            cursor = next_cursor
        return items

    def workflow_count_for_project(self, project_id: str) -> int:
        status, data = self._request(
            "GET",
            "/workflows",
            query={"limit": 1},
            headers={"X-Project-Id": project_id},
        )
        if status != 200 or not isinstance(data, dict):
            raise ApiError(
                f"GET /workflows for project {project_id!r} failed: HTTP {status} body={data!r}"
            )
        items = data.get("items")
        if not isinstance(items, list):
            raise ApiError(f"GET /workflows invalid payload for project {project_id!r}: {data!r}")
        if len(items) > 0:
            return 1
        return 0

    def delete_project(self, project_id: str) -> bool:
        status, data = self._request("DELETE", f"/projects/{project_id}")
        if status in (200, 204, 404):
            return True
        if status == 409:
            return False
        raise ApiError(f"DELETE /projects/{project_id} failed: HTTP {status} body={data!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete empty projects (projects with zero workflows) via WorkCore API."
        )
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="API base URL, for example http://127.0.0.1:8000 or https://api.hq21.tech",
    )
    parser.add_argument(
        "--auth-token",
        default=os.getenv("WORKCORE_API_AUTH_TOKEN", "").strip(),
        help="Bearer token. Defaults to WORKCORE_API_AUTH_TOKEN env.",
    )
    parser.add_argument(
        "--tenant-id",
        default=(os.getenv("E2E_TENANT_ID") or os.getenv("WORKCORE_TENANT_ID") or "local").strip(),
        help="Tenant header value (X-Tenant-Id). Default: local.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP request timeout seconds. Default: 20.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use only for local/self-signed endpoints).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates only (default).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply_mode = bool(args.apply)
    if args.dry_run:
        apply_mode = False

    client = ApiClient(
        base_url=str(args.base_url),
        auth_token=str(args.auth_token).strip() or None,
        tenant_id=str(args.tenant_id).strip() or None,
        timeout_s=float(args.timeout),
        insecure_tls=bool(args.insecure),
    )

    projects = client.list_projects()
    print(f"[cleanup] scanned projects: {len(projects)}")

    empty_project_ids: List[str] = []
    for item in projects:
        project_id = item.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            continue
        normalized = project_id.strip()
        workflow_count = client.workflow_count_for_project(normalized)
        if workflow_count == 0:
            empty_project_ids.append(normalized)

    print(f"[cleanup] empty projects: {len(empty_project_ids)}")
    for project_id in empty_project_ids:
        print(f"  - {project_id}")

    if not apply_mode:
        print("[cleanup] dry-run mode; nothing deleted")
        return 0

    deleted = 0
    skipped_conflict = 0
    for project_id in empty_project_ids:
        ok = client.delete_project(project_id)
        if ok:
            deleted += 1
            print(f"[cleanup] deleted: {project_id}")
        else:
            skipped_conflict += 1
            print(f"[cleanup] skipped (not empty anymore): {project_id}")

    print(
        f"[cleanup] done: deleted={deleted} skipped_conflict={skipped_conflict} total_candidates={len(empty_project_ids)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"[cleanup] error: {exc}", file=sys.stderr)
        raise SystemExit(1)

"""Revision-validated serialized snapshot cache; source records always stay in SQL."""

import hashlib
import json
import threading
from collections import OrderedDict
from contextlib import closing

from starlette.responses import Response


class SnapshotReader:
    def __init__(self, database, kronos_read, max_bytes=8_000_000):
        self.database, self.kronos_read, self.max_bytes = database, kronos_read, max_bytes
        self.cache: OrderedDict[tuple, bytes] = OrderedDict()
        self.lock = threading.Lock()
        self.hits = self.misses = self.bytes = 0

    def read(self, run_id, request, *, limit=50, offset=0, lane=None):
        where = "run_id=?" + (" AND lane=?" if lane else "")
        params = (str(run_id), lane, limit, offset) if lane else (str(run_id), limit, offset)
        with closing(self.database.connect()) as db:
            versions = db.execute(
                f"SELECT id, lane, revision, updated_at FROM research_snapshots WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            # Kronos visibility depends on its live promotion policy, not only the snapshot revision.
            cacheable = all(row["lane"] != "kronos" for row in versions)
            key = (
                str(run_id),
                lane,
                limit,
                offset,
                tuple(tuple(row[k] for k in ("id", "revision", "updated_at")) for row in versions),
            )
            tag = 'W/"' + hashlib.sha256(repr(key).encode()).hexdigest() + '"'
            headers = {"Cache-Control": "private, no-cache" if cacheable else "no-store"}
            if cacheable:
                headers["ETag"] = tag
                if request.headers.get("if-none-match") == tag:
                    return Response(status_code=304, headers=headers)
            with self.lock:
                body = self.cache.get(key) if cacheable else None
                if body is not None:
                    self.cache.move_to_end(key)
                    self.hits += 1
            if body is None:
                rows = db.execute(
                    f"SELECT * FROM research_snapshots WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                    params,
                ).fetchall()
                actual = tuple(
                    tuple(row[k] for k in ("id", "revision", "updated_at")) for row in rows
                )
                # A concurrent writer may have committed between the metadata and body reads.
                if actual != key[-1]:
                    headers = {"Cache-Control": "no-store"}
                    cacheable = False
                body = json.dumps(
                    [
                        {
                            "lane": row["lane"],
                            "status": row["status"],
                            "payload": self.kronos_read(run_id).model_dump(mode="json")
                            if row["lane"] == "kronos"
                            else json.loads(row["payload_json"])
                            if row["payload_json"]
                            else None,
                            "error_message": row["error_message"],
                        }
                        for row in rows
                    ],
                    separators=(",", ":"),
                ).encode()
                with self.lock:
                    self.misses += 1
                    if cacheable and len(body) <= self.max_bytes and key not in self.cache:
                        while self.cache and (
                            self.bytes + len(body) > self.max_bytes or len(self.cache) >= 32
                        ):
                            self.bytes -= len(self.cache.popitem(last=False)[1])
                        self.cache[key] = body
                        self.bytes += len(body)
        return Response(body, media_type="application/json", headers=headers)

    def profile(self):
        with self.lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "entries": len(self.cache),
                "bytes": self.bytes,
                "max_bytes": self.max_bytes,
            }

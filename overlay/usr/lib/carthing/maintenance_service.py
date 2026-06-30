"""Authenticated file maintenance carried over the existing CTSP channel."""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import secrets
import subprocess
import time
from pathlib import Path


logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
KEY_PATH = Path(
    os.environ.get(
        "CARTHING_MAINTENANCE_KEY",
        "/var/lib/carthing/maintenance.key",
    )
)
WORK_ROOT = Path("/run/carthing/maintenance")
RUNTIME_LOG = Path("/var/run/carthing/carthing-remote.log")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 24 * 1024
MAX_LOG_LINES = 200
ALLOWED_ROOTS = (Path("/usr/lib/carthing"),)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,80}$")


class MaintenanceError(Exception):
    pass


class MaintenanceService:
    def __init__(self):
        self._key = self._load_key()
        self._uploads = {}
        self._started_at = time.monotonic()
        self.session_id = secrets.token_hex(16)

    @property
    def available(self):
        return self._key is not None

    def handle(self, raw):
        if self._key is None:
            raise MaintenanceError("maintenance key is not provisioned")
        envelope, payload = self._decode(raw)
        request_id = envelope["id"]
        operation = envelope["op"]
        restart = False
        try:
            if operation == "status":
                result = self._status()
            elif operation == "logs":
                result = self._logs(payload)
            elif operation == "put_begin":
                result = self._put_begin(request_id, payload)
            elif operation == "put_chunk":
                result = self._put_chunk(request_id, payload)
            elif operation == "put_commit":
                result, restart = self._put_commit(request_id)
            elif operation == "put_abort":
                result = self._put_abort(request_id)
            elif operation == "restart":
                result = {"ok": True, "stage": "restart", "message": "scheduled"}
                restart = True
            else:
                raise MaintenanceError("unsupported operation")
        except Exception as exc:
            logger.warning(
                "maintenance %s failed: %s",
                operation,
                exc,
            )
            result = {
                "ok": False,
                "stage": operation,
                "message": str(exc)[:240],
            }
        return self._encode(request_id, "result", result), restart

    def _load_key(self):
        try:
            value = KEY_PATH.read_text().strip()
            key = bytes.fromhex(value)
            if len(key) != 32:
                raise ValueError("key must contain 32 bytes")
            return key
        except Exception as exc:
            logger.warning("maintenance disabled: %s", exc)
            return None

    def _decode(self, raw):
        try:
            envelope = json.loads(bytes(raw).decode("utf-8"))
            version = int(envelope.get("version") or 0)
            request_id = str(envelope.get("id") or "")
            session_id = str(envelope.get("session") or "")
            operation = str(envelope.get("op") or "")
            payload64 = str(envelope.get("payload") or "")
            supplied = str(envelope.get("auth") or "")
        except Exception as exc:
            raise MaintenanceError("invalid envelope") from exc
        if (
            version != PROTOCOL_VERSION
            or session_id != self.session_id
            or not _REQUEST_ID.match(request_id)
        ):
            raise MaintenanceError("invalid envelope identity")
        signed = (
            f"{version}\n{session_id}\n{request_id}\n{operation}\n{payload64}"
        ).encode("utf-8")
        expected = hmac.new(self._key, signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise MaintenanceError("authentication failed")
        try:
            payload_raw = base64.b64decode(payload64, validate=True)
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception as exc:
            raise MaintenanceError("invalid payload") from exc
        if not isinstance(payload, dict):
            raise MaintenanceError("payload must be an object")
        return envelope, payload

    def _encode(self, request_id, operation, payload):
        payload_raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload64 = base64.b64encode(payload_raw).decode("ascii")
        signed = (
            f"{PROTOCOL_VERSION}\n{self.session_id}\n"
            f"{request_id}\n{operation}\n{payload64}"
        ).encode("utf-8")
        authentication = hmac.new(
            self._key,
            signed,
            hashlib.sha256,
        ).hexdigest()
        return json.dumps(
            {
                "version": PROTOCOL_VERSION,
                "session": self.session_id,
                "id": request_id,
                "op": operation,
                "payload": payload64,
                "auth": authentication,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _status(self):
        stat = os.statvfs("/")
        return {
            "ok": True,
            "stage": "status",
            "uptime_s": round(time.monotonic() - self._started_at, 1),
            "free_bytes": int(stat.f_bavail * stat.f_frsize),
            "active_uploads": len(self._uploads),
            "transport": "bluetooth_ctsp_l2cap",
        }

    def _logs(self, payload):
        lines = max(1, min(MAX_LOG_LINES, int(payload.get("lines") or 80)))
        try:
            with RUNTIME_LOG.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 64 * 1024))
                text = handle.read().decode("utf-8", "replace")
        except FileNotFoundError:
            text = ""
        selected = "\n".join(text.splitlines()[-lines:])
        if len(selected.encode("utf-8")) > 24 * 1024:
            selected = selected.encode("utf-8")[-24 * 1024:].decode(
                "utf-8",
                "replace",
            )
        return {
            "ok": True,
            "stage": "logs",
            "text": selected,
        }

    def _put_begin(self, request_id, payload):
        target = self._validated_target(payload.get("path"))
        size = int(payload.get("size") or -1)
        digest = str(payload.get("sha256") or "").lower()
        mode = int(payload.get("mode") or 0o644) & 0o777
        if size < 0 or size > MAX_FILE_BYTES:
            raise MaintenanceError("file size exceeds limit")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MaintenanceError("invalid sha256")
        self._put_abort(request_id)
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = WORK_ROOT / f"{request_id}.part"
        handle = temporary.open("wb")
        self._uploads[request_id] = {
            "target": target,
            "temporary": temporary,
            "handle": handle,
            "hasher": hashlib.sha256(),
            "size": size,
            "received": 0,
            "sha256": digest,
            "next_seq": 0,
            "mode": mode,
            "restart": bool(payload.get("restart")),
        }
        return {
            "ok": True,
            "stage": "put_begin",
            "path": str(target),
            "size": size,
        }

    def _put_chunk(self, request_id, payload):
        upload = self._uploads.get(request_id)
        if upload is None:
            raise MaintenanceError("upload is not active")
        sequence = int(payload.get("seq") or 0)
        if sequence != upload["next_seq"]:
            raise MaintenanceError("unexpected chunk sequence")
        try:
            data = base64.b64decode(
                str(payload.get("data") or ""),
                validate=True,
            )
        except Exception as exc:
            raise MaintenanceError("invalid chunk") from exc
        if not data or len(data) > MAX_CHUNK_BYTES:
            raise MaintenanceError("invalid chunk size")
        if upload["received"] + len(data) > upload["size"]:
            raise MaintenanceError("chunk exceeds declared size")
        upload["handle"].write(data)
        upload["hasher"].update(data)
        upload["received"] += len(data)
        upload["next_seq"] += 1
        return {
            "ok": True,
            "stage": "put_chunk",
            "seq": sequence,
            "received": upload["received"],
        }

    def _put_commit(self, request_id):
        upload = self._uploads.get(request_id)
        if upload is None:
            raise MaintenanceError("upload is not active")
        upload["handle"].flush()
        os.fsync(upload["handle"].fileno())
        upload["handle"].close()
        if upload["received"] != upload["size"]:
            self._put_abort(request_id)
            raise MaintenanceError("file size mismatch")
        actual = upload["hasher"].hexdigest()
        if actual != upload["sha256"]:
            self._put_abort(request_id)
            raise MaintenanceError("sha256 mismatch")
        target = upload["target"]
        staging = target.with_name(f".{target.name}.{request_id}.tmp")
        mounted_rw = False
        try:
            subprocess.run(
                ["mount", "-o", "remount,rw", "/"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            mounted_rw = True
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(upload["temporary"], staging)
            os.chmod(staging, upload["mode"])
            os.replace(staging, target)
            os.sync()
        except Exception:
            self._put_abort(request_id)
            raise
        finally:
            try:
                staging.unlink(missing_ok=True)
            except Exception:
                pass
            if mounted_rw:
                subprocess.run(
                    ["mount", "-o", "remount,ro", "/"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        restart = upload["restart"]
        self._put_abort(request_id)
        logger.info(
            "maintenance installed: path=%s size=%d sha256=%s restart=%s",
            target,
            upload["size"],
            actual,
            restart,
        )
        return {
            "ok": True,
            "stage": "put_commit",
            "path": str(target),
            "size": upload["size"],
            "sha256": actual,
            "restart": restart,
        }, restart

    def _put_abort(self, request_id):
        upload = self._uploads.pop(request_id, None)
        if upload is not None:
            try:
                upload["handle"].close()
            except Exception:
                pass
            try:
                upload["temporary"].unlink(missing_ok=True)
            except Exception:
                pass
        return {"ok": True, "stage": "put_abort"}

    @staticmethod
    def _validated_target(value):
        candidate = Path(str(value or ""))
        if not candidate.is_absolute():
            raise MaintenanceError("target path must be absolute")
        normalized = Path(os.path.normpath(str(candidate)))
        if not any(
            normalized == root or root in normalized.parents
            for root in ALLOWED_ROOTS
        ):
            raise MaintenanceError("target path is outside the runtime")
        if normalized == Path("/usr/lib/carthing"):
            raise MaintenanceError("target path must name a file")
        return normalized

"""Card registry, atomic two-sided install/update with rollback, removal to trash, SDK sync."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .constants import LIMITS
from .errors import BoardError
from .fsutil import atomic_write_bytes, atomic_write_json, file_lock
from .host import Host
from .paths import Paths, check_card_id
from .store import SDK_PATH, sdk_sha256
from .validator import Report, validate_manifest, validate_package

logger = logging.getLogger("hermes_board")
META_FILE = ".meta.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CardStore:
    def __init__(self, paths: Paths, db: Any, host: Host, cron_sync: Any = None,
                 on_board: Optional[Callable[[str], bool]] = None) -> None:
        self.paths = paths
        self.db = db
        self.host = host
        self.cron_sync = cron_sync
        self.on_board = on_board or (lambda _cid: False)

    # ── reading ───────────────────────────────────────────────────────────
    def ids(self) -> list[str]:
        if not self.paths.cards_dir.is_dir():
            return []
        out = []
        for item in sorted(self.paths.cards_dir.iterdir()):
            if item.is_dir() and not item.name.startswith(".") and (item / "card.json").exists():
                try:
                    check_card_id(item.name)
                except BoardError:
                    continue
                out.append(item.name)
        return out

    def exists(self, card_id: str) -> bool:
        return (self.paths.card_dir(card_id) / "card.json").is_file()

    def _meta(self, card_id: str) -> dict[str, Any]:
        path = self.paths.card_dir(card_id) / META_FILE
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"revision": 1}

    def info(self, card_id: str) -> dict[str, Any]:
        """Registry entry; ``status`` is ``ok`` or ``invalid`` (with errors)."""
        card_dir = self.paths.card_dir(card_id)
        meta = self._meta(card_id)
        report = Report()
        manifest: Any = None
        try:
            manifest = json.loads((card_dir / "card.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report.error("manifest", "card.json", f"card.json 无法读取：{exc}")
        if manifest is not None:
            validate_manifest(manifest, report)
            if isinstance(manifest, dict) and manifest.get("id") != card_id:
                report.error("manifest", "id", "card.json 中的 id 与目录名不一致")
        if not (card_dir / "index.html").is_file():
            report.error("missing", "index.html", "缺少 index.html")
        manifest = manifest if isinstance(manifest, dict) else {}
        entry: dict[str, Any] = {
            "id": card_id, "title": manifest.get("title", card_id), "description": manifest.get("description", ""),
            "version": manifest.get("version"), "revision": int(meta.get("revision", 1)),
            "sizes": list(manifest.get("sizes") or []), "defaultSize": manifest.get("defaultSize"),
            "source": meta.get("source"), "status": "ok" if not report.errors else "invalid",
        }
        if report.errors:
            entry["errors"] = report.errors
        entry["manifest"] = manifest
        return entry

    def list(self) -> list[dict[str, Any]]:
        return [self.info(cid) for cid in self.ids()]

    def available(self) -> dict[str, dict[str, Any]]:
        """``{id: {"sizes": [...]}}`` for every valid card (layout validation input)."""
        return {c["id"]: {"sizes": c["sizes"]} for c in self.list() if c["status"] == "ok"}

    def manifest(self, card_id: str) -> dict[str, Any]:
        if not self.exists(card_id):
            raise BoardError("not_found", f"卡片 {card_id} 不存在")
        entry = self.info(card_id)
        if entry["status"] != "ok":
            raise BoardError("invalid", f"卡片 {card_id} 不可用", errors=entry.get("errors", []))
        return entry["manifest"]

    def manifests(self) -> dict[str, dict[str, Any]]:
        return {c["id"]: c["manifest"] for c in self.list() if c["status"] == "ok"}

    def document(self, card_id: str) -> dict[str, Any]:
        if not self.exists(card_id):
            raise BoardError("not_found", f"卡片 {card_id} 不存在")
        html = (self.paths.card_dir(card_id) / "index.html").read_text(encoding="utf-8")
        return {"html": html, "sha256": _sha(html), "revision": int(self._meta(card_id).get("revision", 1))}

    def read_package(self, card_id: str) -> dict[str, Any]:
        if not self.exists(card_id):
            raise BoardError("not_found", f"卡片 {card_id} 不存在")
        card_dir = self.paths.card_dir(card_id)
        manifest = json.loads((card_dir / "card.json").read_text(encoding="utf-8"))
        html_path = card_dir / "index.html"
        scripts: dict[str, str] = {}
        scripts_dir = self.paths.card_scripts_dir(card_id)
        if scripts_dir.is_dir():
            for item in sorted(scripts_dir.iterdir()):
                if item.is_file() and item.suffix in (".py", ".sh"):
                    scripts[item.name] = item.read_text(encoding="utf-8")
        return {"manifest": manifest, "html": html_path.read_text(encoding="utf-8") if html_path.is_file() else "",
                "scripts": scripts, "revision": int(self._meta(card_id).get("revision", 1))}

    # ── SDK sync ──────────────────────────────────────────────────────────
    def sync_sdk(self) -> bool:
        """Copy the bundled SDK when the installed copy differs (content hash)."""
        target = self.paths.sdk_file
        wanted = sdk_sha256()
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == wanted:
            return False
        atomic_write_bytes(target, SDK_PATH.read_bytes())
        return True

    # ── install / update ──────────────────────────────────────────────────
    def validate(self, package: Any) -> dict[str, Any]:
        return validate_package(package, self.host.parse_schedule)

    def install(self, package: Any, *, replace: bool = False, source: str = "agent") -> dict[str, Any]:
        result = self.validate(package)
        if result["errors"]:
            raise BoardError("invalid", "卡片包校验失败", errors=result["errors"], warnings=result["warnings"])
        manifest = package["manifest"]
        card_id = check_card_id(manifest["id"])
        scripts: dict[str, str] = package.get("scripts") or {}
        html: str = package["html"]
        self.paths.cards_dir.mkdir(parents=True, exist_ok=True)
        self.paths.scripts_root.mkdir(parents=True, exist_ok=True)
        with file_lock(self.paths.install_lock):
            card_dir = self.paths.card_dir(card_id)
            scripts_dir = self.paths.card_scripts_dir(card_id)
            existed = (card_dir / "card.json").is_file()
            if existed and not replace:
                raise BoardError("exists", f"卡片 {card_id} 已存在；更新时请传 replace: true")
            old_manifest = None
            revision = 1
            if existed:
                revision = int(self._meta(card_id).get("revision", 1)) + 1
                try:
                    old_manifest = json.loads((card_dir / "card.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    old_manifest = None
            token = uuid.uuid4().hex[:8]
            stage_card = self.paths.cards_dir / f".staging-{card_id}-{token}"
            stage_scripts = self.paths.scripts_root / f".staging-{card_id}-{token}"
            backup_card = self.paths.cards_dir / f".backup-{card_id}-{token}"
            backup_scripts = self.paths.scripts_root / f".backup-{card_id}-{token}"
            moved = {"card_backup": False, "card_new": False, "scripts_backup": False, "scripts_new": False}
            try:
                stage_card.mkdir(parents=True)
                atomic_write_json(stage_card / "card.json", manifest)
                atomic_write_bytes(stage_card / "index.html", html.encode("utf-8"))
                atomic_write_json(stage_card / META_FILE, {"revision": revision, "installedAt": _now_iso(),
                                                           "source": source, "sha256": _sha(html)})
                stage_scripts.mkdir(parents=True)
                for name, content in scripts.items():
                    target = self.paths.script_file(card_id, name)  # validates naming again
                    staged = stage_scripts / target.name
                    atomic_write_bytes(staged, content.encode("utf-8"))
                    os.chmod(staged, 0o755 if name.endswith(".sh") else 0o644)
                if card_dir.exists():
                    os.rename(card_dir, backup_card)
                    moved["card_backup"] = True
                os.rename(stage_card, card_dir)
                moved["card_new"] = True
                if scripts_dir.exists():
                    os.rename(scripts_dir, backup_scripts)
                    moved["scripts_backup"] = True
                os.rename(stage_scripts, scripts_dir)
                moved["scripts_new"] = True
                self.sync_sdk()
                if self.cron_sync is not None:
                    self.cron_sync.sync_card(card_id, manifest, self.on_board(card_id))
            except BaseException as exc:
                self._rollback(card_id, moved, card_dir, scripts_dir, backup_card, backup_scripts, old_manifest)
                for leftover in (stage_card, stage_scripts):
                    shutil.rmtree(leftover, ignore_errors=True)
                if isinstance(exc, BoardError):
                    raise
                if isinstance(exc, Exception):
                    raise BoardError("invalid", f"安装卡片 {card_id} 失败，已回滚：{exc}") from exc
                raise
            for leftover in (backup_card, backup_scripts):
                shutil.rmtree(leftover, ignore_errors=True)
        self.db.add_change(card_id, "card", None)
        return {"card": card_id, "revision": revision, "created": not existed, "warnings": result["warnings"]}

    def _rollback(self, card_id: str, moved: dict[str, bool], card_dir: Path, scripts_dir: Path, backup_card: Path,
                  backup_scripts: Path, old_manifest: Optional[dict[str, Any]]) -> None:
        if moved["scripts_new"]:
            shutil.rmtree(scripts_dir, ignore_errors=True)
        if moved["scripts_backup"]:
            os.rename(backup_scripts, scripts_dir)
        if moved["card_new"]:
            shutil.rmtree(card_dir, ignore_errors=True)
        if moved["card_backup"]:
            os.rename(backup_card, card_dir)
        if self.cron_sync is None:
            return
        try:
            if old_manifest is not None:
                self.cron_sync.sync_card(card_id, old_manifest, self.on_board(card_id))
            else:
                self.cron_sync.remove_card(card_id)
        except Exception as exc:  # pragma: no cover - logged, the original error is what matters
            logger.warning("hermes-board: cron rollback for %s failed: %s", card_id, exc)

    # ── delete ────────────────────────────────────────────────────────────
    def delete(self, card_id: str) -> dict[str, Any]:
        with file_lock(self.paths.install_lock):
            card_dir = self.paths.card_dir(card_id)
            scripts_dir = self.paths.card_scripts_dir(card_id)
            if not card_dir.exists():
                raise BoardError("not_found", f"卡片 {card_id} 不存在")
            if self.cron_sync is not None:
                self.cron_sync.remove_card(card_id)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            trash = self.paths.trash_dir / f"{card_id}-{stamp}"
            trash.mkdir(parents=True)
            os.rename(card_dir, trash / "card")
            if scripts_dir.exists():
                os.rename(scripts_dir, trash / "scripts")
            self.db.delete_card_data(card_id)
        return {"card": card_id, "trash": str(trash)}

    def size_ok(self, html: str) -> bool:
        return len(html.encode("utf-8")) <= LIMITS["htmlBytes"]


__all__ = ["CardStore", "META_FILE"]

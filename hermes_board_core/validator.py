"""Card package validator (design §11–12). Errors block install; warnings are returned."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from .constants import CARD_SCHEMA, LIMITS, PRESETS
from .paths import AI_NAME_RE, CARD_ID_RE, KEY_RE, SCRIPT_FILE_RE, SCRIPT_NAME_RE

SCHEMA_KEYS = {"type", "properties", "required", "enum", "minimum", "maximum", "maxLength", "items",
               "additionalProperties", "description"}
SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
MANIFEST_REQUIRED = ("schema", "id", "title", "description", "version", "entry", "sizes", "defaultSize")
MANIFEST_OPTIONAL = ("scripts", "datasets", "series", "state", "ai")
SCRIPT_KEYS = {"file", "schedule", "runOnInstall", "callable", "timeoutSec", "minIntervalSec", "args", "description"}
DATASET_KEYS = {"description"}
SERIES_KEYS = {"description", "retention"}
RETENTION_KEYS = {"maxAgeDays", "maxPoints"}
STATE_KEYS = {"description", "default"}
AI_KEYS = {"description", "system", "inputSchema", "outputSchema", "maxTokens"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

EXTERNAL_PATTERNS = [
    re.compile(r"""\b(?:src|href|action|poster|srcset|data)\s*=\s*["']?\s*(?:https?:|//)""", re.I),
    re.compile(r"""url\(\s*["']?\s*(?:https?:|//)""", re.I),
    re.compile(r"@import\b", re.I),
]
FORBIDDEN_TAGS = [
    ("base", re.compile(r"<base\b", re.I)),
    ("iframe", re.compile(r"<iframe\b", re.I)),
    ("object", re.compile(r"<object\b", re.I)),
    ("embed", re.compile(r"<embed\b", re.I)),
    ("form action", re.compile(r"<form\b[^>]*\baction\s*=", re.I)),
]
FORBIDDEN_TOKENS = [
    ("fetch(", re.compile(r"(?<![\w$.])fetch\s*\(")),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("WebSocket", re.compile(r"\bWebSocket\b")),
    ("EventSource", re.compile(r"\bEventSource\b")),
    ("sendBeacon", re.compile(r"\bsendBeacon\b")),
    ("localStorage", re.compile(r"\blocalStorage\b")),
    ("sessionStorage", re.compile(r"\bsessionStorage\b")),
    ("indexedDB", re.compile(r"\bindexedDB\b")),
    ("document.cookie", re.compile(r"\bdocument\s*\.\s*cookie\b")),
    ("window.open", re.compile(r"\bwindow\s*\.\s*open\s*\(")),
    ("parent.", re.compile(r"(?<![\w$.])parent\s*\.|\bwindow\s*\.\s*parent\b")),
    ("top.", re.compile(r"(?<![\w$.-])top\s*\.|\bwindow\s*\.\s*top\b")),
]
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.I | re.S)
STYLE_ATTR_RE = re.compile(r"""\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
DECL_RE = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;{}]+)")
VAR_RE = re.compile(r"var\([^()]*(?:\([^()]*\)[^()]*)*\)")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(", re.I)
GRADIENT_RE = re.compile(r"\b(?:repeating-)?(?:linear|radial|conic)-gradient\(", re.I)
ALLOWED_WEIGHTS = {"300", "400", "600", "normal", "inherit", "initial", "unset"}
MAIN_CARD_RE = re.compile(r"""<main\b[^>]*\bclass\s*=\s*["'][^"']*\bhb-card\b""", re.I)
LANG_RE = re.compile(r"""<html\b[^>]*\blang\s*=\s*["']zh-CN["']""", re.I)
USES_DATA_RE = re.compile(r"HermesCard\s*\.\s*(?:data|series|run|scripts|ai|runs)\b")
HANDLES_STATES_RE = re.compile(r"HermesCard\s*\.\s*ui\s*\.\s*state\b|\bhb-state\b")


class Report:
    def __init__(self) -> None:
        self.errors: list[dict[str, str]] = []
        self.warnings: list[dict[str, str]] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append({"code": code, "path": path, "message": message})

    def warn(self, code: str, path: str, message: str) -> None:
        self.warnings.append({"code": code, "path": path, "message": message})

    def as_dict(self) -> dict[str, Any]:
        return {"ok": not self.errors, "errors": self.errors, "warnings": self.warnings}


# ── JSON Schema subset ────────────────────────────────────────────────────

def check_schema(schema: Any, path: str, report: Report) -> None:
    if not isinstance(schema, dict):
        report.error("schema", path, "Schema 必须是对象")
        return
    extra = set(schema) - SCHEMA_KEYS
    if extra:
        report.error("schema", path, f"Schema 使用了不支持的关键字：{sorted(extra)}（仅支持 {sorted(SCHEMA_KEYS)}）")
    typ = schema.get("type")
    if typ is not None and (not isinstance(typ, str) or typ not in SCHEMA_TYPES):
        report.error("schema", f"{path}.type", f"不支持的类型：{typ!r}")
    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            report.error("schema", f"{path}.properties", "properties 必须是对象")
        else:
            for key, sub in props.items():
                check_schema(sub, f"{path}.properties.{key}", report)
    req = schema.get("required")
    if req is not None and (not isinstance(req, list) or not all(isinstance(r, str) for r in req)):
        report.error("schema", f"{path}.required", "required 必须是字符串数组")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        report.error("schema", f"{path}.enum", "enum 必须是非空数组")
    for key in ("minimum", "maximum"):
        if key in schema and (not isinstance(schema[key], (int, float)) or isinstance(schema[key], bool)):
            report.error("schema", f"{path}.{key}", f"{key} 必须是数字")
    if "maxLength" in schema and (not isinstance(schema["maxLength"], int) or schema["maxLength"] < 0):
        report.error("schema", f"{path}.maxLength", "maxLength 必须是非负整数")
    if "items" in schema:
        check_schema(schema["items"], f"{path}.items", report)
    ap = schema.get("additionalProperties")
    if ap is not None and not isinstance(ap, bool):
        check_schema(ap, f"{path}.additionalProperties", report)


def _type_ok(typ: str, value: Any) -> bool:
    if typ == "object":
        return isinstance(value, dict)
    if typ == "array":
        return isinstance(value, list)
    if typ == "string":
        return isinstance(value, str)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "null":
        return value is None
    return True


def validate_value(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    """Validate ``value`` against the supported subset; returns human-readable errors."""
    errors: list[str] = []
    typ = schema.get("type")
    if typ and not _type_ok(typ, value):
        return [f"{path} 应为 {typ}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} 必须是 {schema['enum']} 之一")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} 不能小于 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} 不能大于 {schema['maximum']}")
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{path} 长度不能超过 {schema['maxLength']}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errors.extend(validate_value(schema["items"], item, f"{path}[{i}]"))
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or ():
            if key not in value:
                errors.append(f"{path}.{key} 是必填项")
        ap = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                errors.extend(validate_value(props[key], item, f"{path}.{key}"))
            elif ap is False:
                errors.append(f"{path}.{key} 不是允许的字段")
            elif isinstance(ap, dict):
                errors.extend(validate_value(ap, item, f"{path}.{key}"))
    return errors


# ── manifest ──────────────────────────────────────────────────────────────

def _unknown(obj: dict, allowed: set, path: str, report: Report) -> None:
    extra = set(obj) - allowed
    if extra:
        report.error("manifest", path, f"未知字段：{sorted(extra)}")


def _pos_int(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def validate_manifest(manifest: Any, report: Report, script_files: Optional[set[str]] = None,
                      parse_schedule: Optional[Callable[[str], Any]] = None) -> None:
    if not isinstance(manifest, dict):
        report.error("manifest", "manifest", "清单必须是 JSON 对象")
        return
    for key in MANIFEST_REQUIRED:
        if key not in manifest:
            report.error("manifest", key, f"缺少必填字段 {key}")
    _unknown(manifest, set(MANIFEST_REQUIRED) | set(MANIFEST_OPTIONAL), "manifest", report)
    if manifest.get("schema", CARD_SCHEMA) != CARD_SCHEMA:
        report.error("manifest", "schema", f"schema 必须是 {CARD_SCHEMA}")
    cid = manifest.get("id")
    if "id" in manifest and (not isinstance(cid, str) or not CARD_ID_RE.match(cid)):
        report.error("naming", "id", f"卡片 id 不合法：{cid!r}（需匹配 {CARD_ID_RE.pattern}）")
    title = manifest.get("title")
    if "title" in manifest and (not isinstance(title, str) or not 1 <= len(title) <= 40):
        report.error("manifest", "title", "title 必须是 1–40 个字符的字符串")
    desc = manifest.get("description")
    if "description" in manifest and (not isinstance(desc, str) or len(desc) > 200):
        report.error("manifest", "description", "description 必须是不超过 200 个字符的字符串")
    if "version" in manifest and not (isinstance(manifest["version"], str) and VERSION_RE.match(manifest["version"])):
        report.error("manifest", "version", "version 必须形如 1.0.0")
    if "entry" in manifest and manifest["entry"] != "index.html":
        report.error("manifest", "entry", "entry 必须是 index.html")
    sizes = manifest.get("sizes")
    if "sizes" in manifest:
        if not isinstance(sizes, list) or not sizes:
            report.error("manifest", "sizes", "sizes 必须是非空数组")
            sizes = []
        else:
            bad = [s for s in sizes if s not in PRESETS]
            if bad:
                report.error("manifest", "sizes", f"sizes 含非预设尺寸 {bad}（预设：{', '.join(PRESETS)}）")
            if len(set(map(str, sizes))) != len(sizes):
                report.error("manifest", "sizes", "sizes 有重复项")
    if "defaultSize" in manifest and manifest.get("defaultSize") not in (sizes or []):
        report.error("manifest", "defaultSize", f"defaultSize {manifest.get('defaultSize')!r} 不在 sizes 中")

    scripts = manifest.get("scripts", {})
    if not isinstance(scripts, dict):
        report.error("manifest", "scripts", "scripts 必须是对象")
        scripts = {}
    for name, decl in scripts.items():
        path = f"scripts.{name}"
        if not SCRIPT_NAME_RE.match(name):
            report.error("naming", path, f"脚本名不合法：{name!r}（需匹配 {SCRIPT_NAME_RE.pattern}）")
        if not isinstance(decl, dict):
            report.error("manifest", path, "脚本声明必须是对象")
            continue
        _unknown(decl, SCRIPT_KEYS, path, report)
        file_name = decl.get("file")
        if not isinstance(file_name, str) or not SCRIPT_FILE_RE.match(file_name):
            report.error("naming", f"{path}.file", f"脚本文件名不合法：{file_name!r}（需匹配 {SCRIPT_FILE_RE.pattern}）")
        elif script_files is not None and file_name not in script_files:
            report.error("missing", f"{path}.file", f"脚本文件 {file_name} 不在卡片包里")
        if "schedule" in decl:
            sched = decl["schedule"]
            if not isinstance(sched, str) or not sched.strip():
                report.error("schedule", f"{path}.schedule", "schedule 必须是非空字符串")
            elif parse_schedule is not None:
                try:
                    parse_schedule(sched)
                except Exception as exc:  # parser messages vary between Hermes versions
                    report.error("schedule", f"{path}.schedule", f"Hermes cron 无法解析 schedule {sched!r}：{exc}")
        for flag in ("runOnInstall", "callable"):
            if flag in decl and not isinstance(decl[flag], bool):
                report.error("manifest", f"{path}.{flag}", f"{flag} 必须是布尔值")
        if "timeoutSec" in decl and not _pos_int(decl["timeoutSec"], 1, LIMITS["actionTimeoutMax"]):
            report.error("manifest", f"{path}.timeoutSec", f"timeoutSec 必须是 1–{LIMITS['actionTimeoutMax']} 的整数")
        if "minIntervalSec" in decl and not _pos_int(decl["minIntervalSec"], 0, 86400):
            report.error("manifest", f"{path}.minIntervalSec", "minIntervalSec 必须是 0–86400 的整数")
        if "args" in decl:
            check_schema(decl["args"], f"{path}.args", report)

    for section, allowed in (("datasets", DATASET_KEYS), ("series", SERIES_KEYS), ("state", STATE_KEYS)):
        block = manifest.get(section, {})
        if not isinstance(block, dict):
            report.error("manifest", section, f"{section} 必须是对象")
            continue
        for key, decl in block.items():
            path = f"{section}.{key}"
            if not KEY_RE.match(key):
                report.error("naming", path, f"名称不合法：{key!r}（需匹配 {KEY_RE.pattern}）")
            if not isinstance(decl, dict):
                report.error("manifest", path, "声明必须是对象")
                continue
            _unknown(decl, allowed, path, report)
            if section == "series" and "retention" in decl:
                ret = decl["retention"]
                if not isinstance(ret, dict):
                    report.error("manifest", f"{path}.retention", "retention 必须是对象")
                else:
                    _unknown(ret, RETENTION_KEYS, f"{path}.retention", report)
                    if "maxAgeDays" in ret and not _pos_int(ret["maxAgeDays"], 1, 3650):
                        report.error("manifest", f"{path}.retention.maxAgeDays", "maxAgeDays 必须是 1–3650 的整数")
                    if "maxPoints" in ret and not _pos_int(ret["maxPoints"], 1, 1_000_000):
                        report.error("manifest", f"{path}.retention.maxPoints", "maxPoints 必须是 1–1000000 的整数")
            if section == "state" and "default" in decl:
                try:
                    if len(json.dumps(decl["default"], ensure_ascii=False).encode()) > LIMITS["stateValueBytes"]:
                        report.error("manifest", f"{path}.default", "默认值超过 64 KiB")
                except (TypeError, ValueError):
                    report.error("manifest", f"{path}.default", "默认值必须可序列化为 JSON")

    ai = manifest.get("ai", {})
    if not isinstance(ai, dict):
        report.error("manifest", "ai", "ai 必须是对象")
        ai = {}
    for name, decl in ai.items():
        path = f"ai.{name}"
        if not AI_NAME_RE.match(name):
            report.error("naming", path, f"AI 任务名不合法：{name!r}")
        if not isinstance(decl, dict):
            report.error("manifest", path, "AI 声明必须是对象")
            continue
        _unknown(decl, AI_KEYS, path, report)
        if not isinstance(decl.get("system"), str) or not decl.get("system", "").strip() or len(decl["system"]) > 8000:
            report.error("manifest", f"{path}.system", "system 必须是 1–8000 个字符的提示词")
        for key in ("inputSchema", "outputSchema"):
            if key not in decl:
                report.error("manifest", f"{path}.{key}", f"缺少 {key}")
            else:
                check_schema(decl[key], f"{path}.{key}", report)
        if "maxTokens" in decl and not _pos_int(decl["maxTokens"], 1, LIMITS["aiMaxTokens"]):
            report.error("manifest", f"{path}.maxTokens", f"maxTokens 必须是 1–{LIMITS['aiMaxTokens']} 的整数")


# ── HTML ──────────────────────────────────────────────────────────────────

def _css_text(html: str) -> list[str]:
    chunks = [m.group(1) for m in STYLE_BLOCK_RE.finditer(html)]
    chunks += [m.group(1) or m.group(2) or "" for m in STYLE_ATTR_RE.finditer(html)]
    return chunks


def validate_html(html: Any, manifest: Any, report: Report) -> None:
    if not isinstance(html, str) or not html.strip():
        report.error("missing", "index.html", "缺少入口文件 index.html")
        return
    size = len(html.encode("utf-8"))
    if size > LIMITS["htmlBytes"]:
        report.error("size", "index.html", f"index.html 为 {size} 字节，超过 256 KiB 上限")
    text = HTML_COMMENT_RE.sub("", html)
    for pattern in EXTERNAL_PATTERNS:
        m = pattern.search(text)
        if m:
            report.error("external", "index.html",
                         f"不能引用外部资源（{m.group(0).strip()}…）：样式、脚本和图片都要内联，图片用 data: URL；"
                         "图表请改用运行时提供的 HermesCard.chart，取数放到脚本里")
            break
    for label, pattern in FORBIDDEN_TAGS:
        if pattern.search(text):
            report.error("forbidden", "index.html", f"不能使用 <{label}>")
    for label, pattern in FORBIDDEN_TOKENS:
        if pattern.search(text):
            report.error("forbidden", "index.html",
                         f"不能使用 {label}：卡片不能联网、访问浏览器存储或父窗口，请通过 window.HermesCard 获取数据和执行操作")

    colors, families, shadows, gradients, weights = [], False, False, False, set()
    for css in _css_text(text):
        for prop, value in DECL_RE.findall(css):
            prop_l = prop.lower()
            bare = VAR_RE.sub("", value)
            if COLOR_RE.search(bare):
                colors.append(f"{prop_l}: {value.strip()}")
            if prop_l == "font-family":
                families = True
            if prop_l == "box-shadow" and bare.strip().lower() not in ("none", ""):
                shadows = True
            if GRADIENT_RE.search(bare):
                gradients = True
            if prop_l == "font-weight" and bare.strip().lower() not in ALLOWED_WEIGHTS and bare.strip():
                weights.add(bare.strip())
    if colors:
        report.warn("design.color", "index.html",
                    f"写死了颜色（{'; '.join(colors[:3])}）：建议改用令牌颜色，例如 var(--hb-ink-2)、var(--hb-accent)")
    if families:
        report.warn("design.font", "index.html", "自定义了 font-family：请使用运行时注入的字体栈")
    if shadows:
        report.warn("design.shadow", "index.html", "使用了 box-shadow：卡片内部层次只用表面色和发丝线")
    if gradients:
        report.warn("design.gradient", "index.html", "使用了渐变：卡片内部不用渐变")
    if weights:
        report.warn("design.weight", "index.html", f"使用了字重 {sorted(weights)}：只用 300、400、600")
    if not MAIN_CARD_RE.search(text):
        report.warn("design.root", "index.html", '缺少 <main class="hb-card"> 根元素')
    if not LANG_RE.search(text):
        report.warn("design.lang", "index.html", '缺少 <html lang="zh-CN">')
    uses_data = bool(USES_DATA_RE.search(text))
    if isinstance(manifest, dict) and (manifest.get("datasets") or manifest.get("series")):
        uses_data = True
    if uses_data and not HANDLES_STATES_RE.search(text):
        report.warn("design.states", "index.html", "没有处理加载、空、错误状态：请用 HermesCard.ui.state 或 hb-state")


# ── package ───────────────────────────────────────────────────────────────

def validate_package(package: Any, parse_schedule: Optional[Callable[[str], Any]] = None) -> dict[str, Any]:
    report = Report()
    if not isinstance(package, dict):
        report.error("package", "package", "卡片包必须是对象 {manifest, html, scripts}")
        return report.as_dict()
    extra = set(package) - {"manifest", "html", "scripts"}
    if extra:
        report.error("package", "package", f"卡片包含未知字段：{sorted(extra)}")
    scripts = package.get("scripts") or {}
    files: set[str] = set()
    if not isinstance(scripts, dict):
        report.error("package", "scripts", "scripts 必须是 {文件名: 源码} 对象")
    else:
        for name, source in scripts.items():
            if not isinstance(name, str) or not SCRIPT_FILE_RE.match(name):
                report.error("naming", f"scripts.{name}", f"脚本文件名不合法：{name!r}（需匹配 {SCRIPT_FILE_RE.pattern}）")
                continue
            if not isinstance(source, str):
                report.error("package", f"scripts.{name}", "脚本内容必须是字符串")
                continue
            if len(source.encode("utf-8")) > LIMITS["scriptBytes"]:
                report.error("size", f"scripts.{name}", "脚本超过 256 KiB")
            files.add(name)
            if name.endswith(".py"):
                try:
                    compile(source, name, "exec")
                except SyntaxError as exc:
                    report.warn("script.syntax", f"scripts.{name}", f"Python 语法错误：第 {exc.lineno} 行 {exc.msg}")
    manifest = package.get("manifest")
    validate_manifest(manifest, report, files, parse_schedule)
    validate_html(package.get("html"), manifest, report)
    return report.as_dict()


def load_package_dir(path: Path) -> dict[str, Any]:
    """Read ``card.json`` / ``index.html`` / ``scripts/*`` from a card directory."""
    manifest_path = path / "card.json"
    manifest: Any = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            manifest = None
    html_path = path / "index.html"
    html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    scripts: dict[str, str] = {}
    scripts_dir = path / "scripts"
    if scripts_dir.is_dir():
        for item in sorted(scripts_dir.iterdir()):
            if item.is_file() and not item.name.startswith(".") and item.suffix in (".py", ".sh"):
                scripts[item.name] = item.read_text(encoding="utf-8")
    return {"manifest": manifest, "html": html, "scripts": scripts}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hermes_board_core.validator",
                                     description="校验 hermes-board 卡片包目录（card.json、index.html、scripts/）")
    parser.add_argument("dirs", nargs="+", type=Path)
    parser.add_argument("--strict", action="store_true", help="警告也视为失败")
    args = parser.parse_args(argv)
    from .host import get_host

    failed = False
    for directory in args.dirs:
        if not (directory / "card.json").is_file():
            continue
        result = validate_package(load_package_dir(directory), get_host().parse_schedule)
        bad = result["errors"] or (args.strict and result["warnings"])
        failed = failed or bool(bad)
        status = "FAIL" if bad else "OK"
        print(f"[{status}] {directory}")
        for item in result["errors"]:
            print(f"  error   {item['path']}: {item['message']}")
        for item in result["warnings"]:
            print(f"  warning {item['path']}: {item['message']}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

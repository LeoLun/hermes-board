from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from helpers import BoardTestCase

import cardkit
from hermes_board_core import validator
from hermes_board_core.host import fallback_parse_schedule
from hermes_board_core.validator import validate_package, validate_value


def run(pkg):
    return validate_package(pkg, fallback_parse_schedule)


def codes(result, kind="errors"):
    return [item["code"] for item in result[kind]]


def messages(result, kind="errors"):
    return " | ".join(item["message"] for item in result[kind])


def html_with(body: str = "", style: str = "") -> str:
    return cardkit.HTML.replace("</style>", style + "</style>").replace("</main>", body + "</main>")


class ValidatorErrorsTest(unittest.TestCase):
    def test_valid_package_has_no_errors_or_warnings(self):
        result = run(cardkit.package())
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(result["ok"])

    def test_missing_required_and_unknown_fields(self):
        pkg = cardkit.package()
        del pkg["manifest"]["title"]
        pkg["manifest"]["colour"] = "red"
        result = run(pkg)
        self.assertIn("缺少必填字段 title", messages(result))
        self.assertIn("未知字段", messages(result))

    def test_default_size_not_in_sizes(self):
        result = run(cardkit.package(sizes=["4x4"], defaultSize="8x8"))
        self.assertIn("defaultSize", [e["path"] for e in result["errors"]])

    def test_sizes_must_be_presets(self):
        result = run(cardkit.package(sizes=["4x4", "5x5"]))
        self.assertIn("非预设尺寸", messages(result))

    def test_naming_rules(self):
        result = run(cardkit.package(card_id="Bad_ID"))
        self.assertIn("naming", codes(result))
        result = run(cardkit.package(scripts={"../../evil.py": "print(1)", "fetch.py": cardkit.SCRIPT}))
        self.assertIn("脚本文件名不合法", messages(result))

    def test_declared_script_file_missing(self):
        result = run(cardkit.package(scripts={}))
        self.assertIn("missing", codes(result))

    def test_bad_schedule(self):
        pkg = cardkit.package()
        pkg["manifest"]["scripts"]["fetch"]["schedule"] = "whenever"
        self.assertIn("schedule", codes(run(pkg)))

    def test_schema_subset(self):
        pkg = cardkit.package()
        pkg["manifest"]["scripts"]["fetch"]["args"] = {"type": "object", "oneOf": []}
        self.assertIn("不支持的关键字", messages(run(pkg)))
        pkg = cardkit.package(ai={"pick": {"system": "选择", "inputSchema": {"type": "object"},
                                           "outputSchema": {"type": "object", "patternProperties": {}},
                                           "maxTokens": 4000}})
        result = run(pkg)
        self.assertIn("不支持的关键字", messages(result))
        self.assertIn("maxTokens", messages(result))

    def test_html_size_limit(self):
        big = cardkit.HTML.replace("</main>", "<p>" + "字" * 90000 + "</p></main>")
        self.assertIn("size", codes(run(cardkit.package(html=big))))

    def test_external_cdn_script_points_to_runtime_chart(self):
        html = cardkit.HTML.replace("</head>", '<script src="https://cdn.example.com/chart.js"></script></head>')
        result = run(cardkit.package(html=html))
        self.assertIn("external", codes(result))
        self.assertIn("HermesCard.chart", messages(result))
        for snippet in ('<img src="//x.com/a.png">', '<link href="https://x.com/a.css">'):
            self.assertIn("external", codes(run(cardkit.package(html=html_with(snippet)))), snippet)
        self.assertIn("external", codes(run(cardkit.package(html=html_with(style=".a{background:url(https://x/y.png)}")))))
        self.assertIn("external", codes(run(cardkit.package(html=html_with(style="@import 'x.css';")))))

    def test_forbidden_tags(self):
        for tag in ("<iframe></iframe>", "<object></object>", "<embed>", '<form action="/x"></form>', '<base href="/">'):
            self.assertIn("forbidden", codes(run(cardkit.package(html=html_with(tag)))), tag)

    def test_forbidden_tokens(self):
        for js in ("fetch('/x')", "new XMLHttpRequest()", "new WebSocket('ws://x')", "new EventSource('/e')",
                   "navigator.sendBeacon('/x')", "localStorage.setItem('a',1)", "sessionStorage.clear()",
                   "indexedDB.open('x')", "document.cookie", "window.open('x')", "parent.postMessage(1,'*')",
                   "window.parent.x", "top.location='x'"):
            html = cardkit.HTML.replace("HermesCard.ready();", f"HermesCard.ready(); {js};")
            self.assertIn("forbidden", codes(run(cardkit.package(html=html))), js)

    def test_comments_are_ignored(self):
        html = cardkit.HTML.replace("<main", "<!-- fetch('/x') <iframe> --><main")
        self.assertEqual(run(cardkit.package(html=html))["errors"], [])

    def test_allowed_lookalikes(self):
        html = cardkit.HTML.replace("HermesCard.ready();",
                                    "HermesCard.ready(); var o = {top: 1}; o.top; HermesCard.data.fetchAll;")
        self.assertEqual(run(cardkit.package(html=html))["errors"], [])


class ValidatorWarningsTest(unittest.TestCase):
    def warn_codes(self, html):
        result = run(cardkit.package(html=html))
        self.assertEqual(result["errors"], [], result["errors"])
        return codes(result, "warnings"), messages(result, "warnings")

    def test_hardcoded_color_suggests_token(self):
        found, text = self.warn_codes(html_with(style=".x{color: #333}"))
        self.assertIn("design.color", found)
        self.assertIn("var(--hb-ink-2)", text)
        found, _ = self.warn_codes(html_with(style=".x{color: var(--hb-ink, #333)}"))
        self.assertNotIn("design.color", found)
        found, _ = self.warn_codes(html_with('<p style="background: rgba(0,0,0,.2)">x</p>'))
        self.assertIn("design.color", found)

    def test_design_rules(self):
        cases = {
            "design.font": ".x{font-family: Arial}",
            "design.shadow": ".x{box-shadow: 0 1px 2px var(--hb-hairline)}",
            "design.gradient": ".x{background: linear-gradient(var(--hb-accent), var(--hb-ink))}",
            "design.weight": ".x{font-weight: 700}",
        }
        for code, style in cases.items():
            found, _ = self.warn_codes(html_with(style=style))
            self.assertIn(code, found, code)
        found, _ = self.warn_codes(html_with(style=".x{box-shadow: none; font-weight: 300}.y{font-weight:500}"))
        self.assertFalse({"design.shadow", "design.weight"} & set(found))

    def test_structure_rules(self):
        found, _ = self.warn_codes(cardkit.HTML.replace('class="hb-card"', 'class="card"'))
        self.assertIn("design.root", found)
        found, _ = self.warn_codes(cardkit.HTML.replace(' lang="zh-CN"', ""))
        self.assertIn("design.lang", found)
        no_states = cardkit.HTML.replace("hb-state", "box").replace("HermesCard.ui.state", "console.log")
        found, _ = self.warn_codes(no_states)
        self.assertIn("design.states", found)


class SchemaValueTest(unittest.TestCase):
    def test_validate_value(self):
        schema = {"type": "object", "required": ["node"], "additionalProperties": False,
                  "properties": {"node": {"type": "string", "maxLength": 5},
                                 "n": {"type": "integer", "minimum": 1, "maximum": 3},
                                 "mode": {"enum": ["a", "b"]},
                                 "tags": {"type": "array", "items": {"type": "string"}}}}
        self.assertEqual(validate_value(schema, {"node": "hk", "n": 2, "mode": "a", "tags": ["x"]}), [])
        errors = validate_value(schema, {"n": 9, "mode": "c", "tags": [1], "extra": True, "node": "toolong"})
        joined = " ".join(errors)
        for needle in ("不能大于", "之一", "应为 string", "不是允许的字段", "长度"):
            self.assertIn(needle, joined)
        self.assertIn("必填", " ".join(validate_value(schema, {})))
        self.assertEqual(validate_value({"type": "integer"}, True), ["$ 应为 integer"])


class ValidatorCliTest(BoardTestCase):
    def write_dir(self, pkg):
        directory = self.tmp / pkg["manifest"]["id"]
        (directory / "scripts").mkdir(parents=True)
        (directory / "card.json").write_text(json.dumps(pkg["manifest"], ensure_ascii=False))
        (directory / "index.html").write_text(pkg["html"])
        for name, src in pkg["scripts"].items():
            (directory / "scripts" / name).write_text(src)
        return directory

    def test_cli_strict(self):
        ok_dir = self.write_dir(cardkit.package("good"))
        warn_dir = self.write_dir(cardkit.package("warny", html=html_with(style=".x{color:#333}")))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(validator.main([str(ok_dir), str(warn_dir)]), 0)
            self.assertEqual(validator.main([str(warn_dir), "--strict"]), 1)
        self.assertIn("warning", out.getvalue())


if __name__ == "__main__":
    unittest.main()

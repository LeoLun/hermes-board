from __future__ import annotations

import importlib.util
import unittest

from helpers import ROOT

from hermes_board_core import ai


class FakeCtx:
    def __init__(self, llm=None):
        self.skills = []
        self.tools = []
        self.llm = llm

    def register_skill(self, name, path, description=""):
        self.skills.append({"name": name, "path": path, "description": description})

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


def load_plugin():
    spec = importlib.util.spec_from_file_location("hermes_board_plugin_under_test", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegistrationTest(unittest.TestCase):
    def tearDown(self):
        ai.set_llm(None)

    def test_register(self):
        llm = object()
        ctx = FakeCtx(llm=llm)
        load_plugin().register(ctx)
        self.assertEqual([t["name"] for t in ctx.tools], ["board_manage"])
        tool = ctx.tools[0]
        self.assertEqual(tool["toolset"], "hermes_board")
        self.assertEqual(tool["schema"]["name"], "board_manage")
        self.assertTrue(callable(tool["handler"]))
        self.assertEqual([s["name"] for s in ctx.skills], ["card-author"])
        self.assertTrue(ctx.skills[0]["path"].is_file())
        self.assertIs(ai.get_llm(), llm, "the dashboard API shares the same hermes_board_core.ai module")

    def test_register_without_llm(self):
        ctx = FakeCtx()
        load_plugin().register(ctx)
        self.assertEqual(len(ctx.tools), 1)

    def test_manifest_files(self):
        text = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        for needle in ("name: hermes-board", "board_manage", "requires_hermes"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()

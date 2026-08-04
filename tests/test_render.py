#!/usr/bin/env python3
"""Unit tests for the pure parts: config merge, counting, title rendering.

Run: python3 tests/test_render.py
"""

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module():
    path = os.path.join(ROOT, "bin", "herdr-ghostty-title")
    spec = importlib.util.spec_from_loader(
        "hgt", importlib.machinery.SourceFileLoader("hgt", path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hgt = load_module()


def cfg(**overrides):
    base = hgt.load_config()
    base["label"] = "host"
    base.update(overrides)
    return base


class TestCounting(unittest.TestCase):
    def test_counts_by_status(self):
        agents = [
            {"agent_status": "idle"},
            {"agent_status": "idle"},
            {"agent_status": "working"},
            {"agent_status": "blocked"},
            {"agent_status": "done"},
        ]
        counts = hgt.count_statuses(agents)
        self.assertEqual(counts["idle"], 2)
        self.assertEqual(counts["working"], 1)
        self.assertEqual(counts["blocked"], 1)
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["unknown"], 0)

    def test_missing_and_bogus_status_becomes_unknown(self):
        counts = hgt.count_statuses([{}, {"agent_status": "wat"}, {"agent_status": None}])
        self.assertEqual(counts["unknown"], 3)

    def test_empty_and_none(self):
        self.assertEqual(hgt.count_statuses([])["idle"], 0)
        self.assertEqual(hgt.count_statuses(None)["idle"], 0)


class TestRender(unittest.TestCase):
    def test_default_shape(self):
        counts = hgt.count_statuses(
            [{"agent_status": "blocked"}] * 2
            + [{"agent_status": "working"}] * 5
            + [{"agent_status": "idle"}] * 12
        )
        self.assertEqual(render(counts), "host  \U0001f534 2  \U0001f7e1 5  ⚪ 12")

    def test_zeros_hidden_by_default(self):
        counts = hgt.count_statuses([{"agent_status": "done"}])
        self.assertEqual(render(counts), "host  \U0001f7e2 1")

    def test_zeros_shown_when_configured(self):
        counts = hgt.count_statuses([{"agent_status": "done"}])
        title = render(counts, hide_zero=False)
        self.assertEqual(title, "host  \U0001f534 0  \U0001f7e2 1  \U0001f7e1 0  ⚪ 0")

    def test_no_agents_gives_label_only(self):
        self.assertEqual(render(hgt.count_statuses([])), "host")

    def test_no_agents_with_empty_text(self):
        self.assertEqual(render(hgt.count_statuses([]), empty_text="idle"), "host  idle")

    def test_label_can_be_dropped(self):
        counts = hgt.count_statuses([{"agent_status": "blocked"}])
        self.assertEqual(render(counts, label=""), "\U0001f534 1")

    def test_show_order_is_respected(self):
        counts = hgt.count_statuses(
            [{"agent_status": "blocked"}, {"agent_status": "idle"}]
        )
        self.assertEqual(
            render(counts, show=["idle", "blocked"]), "host  ⚪ 1  \U0001f534 1"
        )

    def test_unknown_can_be_shown(self):
        counts = hgt.count_statuses([{}])
        self.assertEqual(
            render(counts, show=["unknown"]), "host  ⚫ 1"
        )

    def test_unknown_hidden_by_default(self):
        counts = hgt.count_statuses([{}, {}])
        self.assertEqual(render(counts), "host")

    def test_custom_glyphs_and_separators(self):
        counts = hgt.count_statuses(
            [{"agent_status": "blocked"}, {"agent_status": "working"}]
        )
        title = render(
            counts,
            glyphs={"blocked": "!", "working": "~", "done": "+", "idle": ".", "unknown": "?"},
            count_separator="",
            item_separator=" ",
            label_separator=" | ",
        )
        self.assertEqual(title, "host | !1 ~1")

    def test_control_characters_are_stripped(self):
        counts = hgt.count_statuses([{"agent_status": "idle"}])
        self.assertEqual(render(counts, label="ho\x07st\x1b"), "host  ⚪ 1")

    def test_long_titles_are_truncated(self):
        counts = hgt.count_statuses([{"agent_status": "idle"}])
        title = render(counts, label="x" * 200, max_title_chars=20)
        self.assertEqual(len(title), 20)
        self.assertTrue(title.endswith("…"))

    def test_no_truncation_when_limit_zero(self):
        counts = hgt.count_statuses([{"agent_status": "idle"}])
        title = render(counts, label="x" * 200, max_title_chars=0)
        self.assertTrue(len(title) > 200)


class TestConfig(unittest.TestCase):
    def test_defaults_are_sane(self):
        c = hgt.load_config()
        self.assertEqual(c["show"], ["blocked", "done", "working", "idle"])
        self.assertTrue(c["label"])  # hostname fallback

    def test_label_env_override(self):
        os.environ["HERDR_GHOSTTY_TITLE_LABEL"] = "envhost"
        try:
            self.assertEqual(hgt.load_config()["label"], "envhost")
        finally:
            del os.environ["HERDR_GHOSTTY_TITLE_LABEL"]

    def test_bogus_show_falls_back_to_defaults(self):
        merged = hgt._deep_merge(hgt.DEFAULTS, {"show": ["nope"]})
        self.assertEqual(merged["show"], ["nope"])  # merge is dumb by design
        # ...but load_config filters. Simulate via a temp json config.
        import json
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"show": ["nope", "blocked"]}, fh)
            path = fh.name
        os.environ["HERDR_GHOSTTY_TITLE_CONFIG"] = path
        try:
            self.assertEqual(hgt.load_config()["show"], ["blocked"])
        finally:
            del os.environ["HERDR_GHOSTTY_TITLE_CONFIG"]
            os.unlink(path)

    def test_deep_merge_keeps_unspecified_glyphs(self):
        merged = hgt._deep_merge(hgt.DEFAULTS, {"glyphs": {"idle": "z"}})
        self.assertEqual(merged["glyphs"]["idle"], "z")
        self.assertEqual(merged["glyphs"]["blocked"], hgt.DEFAULTS["glyphs"]["blocked"])

    def test_json_config_is_read(self):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"label": "fromjson", "hide_zero": False}, fh)
            path = fh.name
        os.environ["HERDR_GHOSTTY_TITLE_CONFIG"] = path
        try:
            c = hgt.load_config()
            self.assertEqual(c["label"], "fromjson")
            self.assertFalse(c["hide_zero"])
        finally:
            del os.environ["HERDR_GHOSTTY_TITLE_CONFIG"]
            os.unlink(path)

    def test_toml_config_is_read(self):
        try:
            import tomllib  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("tomllib requires python >= 3.11")
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write('label = "fromtoml"\n[glyphs]\nidle = "z"\n')
            path = fh.name
        os.environ["HERDR_GHOSTTY_TITLE_CONFIG"] = path
        try:
            c = hgt.load_config()
            self.assertEqual(c["label"], "fromtoml")
            self.assertEqual(c["glyphs"]["idle"], "z")
            self.assertEqual(c["glyphs"]["blocked"], hgt.DEFAULTS["glyphs"]["blocked"])
        finally:
            del os.environ["HERDR_GHOSTTY_TITLE_CONFIG"]
            os.unlink(path)


def render(counts, **overrides):
    return hgt.render_title(counts, cfg(**overrides))


if __name__ == "__main__":
    unittest.main(verbosity=2)

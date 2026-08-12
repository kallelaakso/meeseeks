from __future__ import annotations

import unittest

from orchestrator.tickets import (
    artifact_glob,
    branch,
    parse_branch,
    parse_depends_on,
    plan_path,
    render_artifacts_block,
    slugify,
    spec_path,
    upsert_artifacts_block,
)


class TestSlugify(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_replaces_punctuation_with_dash(self):
        self.assertEqual(slugify("a!b@c#d"), "a-b-c-d")

    def test_collapses_repeated_dashes(self):
        self.assertEqual(slugify("a!!!b"), "a-b")

    def test_strips_leading_trailing_dashes(self):
        self.assertEqual(slugify("-hello-"), "hello")

    def test_truncates_to_40(self):
        long_title = "a" * 50
        result = slugify(long_title)
        self.assertLessEqual(len(result), 40)

    def test_unicode(self):
        self.assertEqual(slugify("café déjà"), "caf-d-j")


class TestBranch(unittest.TestCase):
    def test_branch_format(self):
        self.assertEqual(branch("spec", 1, "foo"), "meeseeks/spec/1-foo")

    def test_parse_branch_valid_spec(self):
        self.assertEqual(parse_branch("meeseeks/spec/42-title"), ("spec", 42))

    def test_parse_branch_valid_impl(self):
        self.assertEqual(parse_branch("meeseeks/impl/7-fix"), ("impl", 7))

    def test_parse_branch_rejects_plan(self):
        self.assertIsNone(parse_branch("plan/foo"))

    def test_parse_branch_rejects_non_numeric(self):
        self.assertIsNone(parse_branch("meeseeks/impl/abc-x"))

    def test_parse_branch_rejects_foreign(self):
        self.assertIsNone(parse_branch("feature/foo"))


class TestPaths(unittest.TestCase):
    def test_spec_path(self):
        self.assertEqual(spec_path(3, "foo"), "docs/spec/3-foo.md")

    def test_plan_path(self):
        self.assertEqual(plan_path(3, "foo"), "docs/plan/3-foo.md")

    def test_artifact_glob(self):
        self.assertEqual(artifact_glob(3, "ready"), "docs/ready/3-*.md")


class TestParseDependsOn(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(parse_depends_on("no deps here"), [])

    def test_one_with_colon(self):
        self.assertEqual(parse_depends_on("Depends on: #42"), [42])

    def test_one_without_colon(self):
        self.assertEqual(parse_depends_on("Depends on #42"), [42])

    def test_many(self):
        body = "Depends on: #1, #2, #3"
        self.assertEqual(parse_depends_on(body), [1, 2, 3])

    def test_dedupes(self):
        body = "Depends on: #1\nDepends on: #1"
        self.assertEqual(parse_depends_on(body), [1])


class TestArtifactsBlock(unittest.TestCase):
    def test_render(self):
        block = render_artifacts_block("s", "p", 5, "http://r")
        self.assertIn("Spec:", block)
        self.assertIn("Plan:", block)
        self.assertIn("#5", block)

    def test_upsert_appends_when_missing(self):
        body = "Hello"
        block = "<!-- meeseeks:artifacts -->\nX\n<!-- /meeseeks:artifacts -->"
        result = upsert_artifacts_block(body, block)
        self.assertIn("Hello", result)
        self.assertIn("X", result)

    def test_upsert_replaces_when_present(self):
        body = "A\n<!-- meeseeks:artifacts -->\nOLD\n<!-- /meeseeks:artifacts -->\nB"
        block = "<!-- meeseeks:artifacts -->\nNEW\n<!-- /meeseeks:artifacts -->"
        result = upsert_artifacts_block(body, block)
        self.assertIn("NEW", result)
        self.assertNotIn("OLD", result)
        self.assertIn("A", result)
        self.assertIn("B", result)

    def test_upsert_idempotent(self):
        body = "Hello"
        block = "<!-- meeseeks:artifacts -->\nX\n<!-- /meeseeks:artifacts -->"
        first = upsert_artifacts_block(body, block)
        second = upsert_artifacts_block(first, block)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

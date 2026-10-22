"""Exercise manual review gates against temporary books, never real manuscripts."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import local_workbench as workbench
from src.local_preview import app


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "book"
        self.data = Path(self.temp.name) / "data"
        self.files = {
            "AGENTS.md": "中文。正文事实优先。",
            "正文/第001章_开篇.md": "第一章正文。\n",
            "正文/第002章_接续.md": "第二章正文。\n",
            "正文/阅读入口.md": "[第一章](第001章_开篇.md)\n[第二章](第002章_接续.md)",
            "大纲/细纲_第002章.md": "第二章细纲。",
            "大纲/细纲_第004章.md": "第四章细纲。",
            "写作规范/文风规则.md": "大白话，句号后换段。",
            "写作规范/正文验收清单.md": "核对事实、人物、因果。",
            "追踪/上下文.md": "第一章结束。",
            "设定/角色/主角.md": "主角只知道现场的信息。",
        }
        for relative, text in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.config = {"title": "测试书", "root": self.root, "manuscript": "正文", "outlines": ["大纲"],
                       "genre": "测试", "focus": "保持事实", "skills": {}, "core": []}
        self.books_patch = patch.dict(workbench.BOOKS, {"test": self.config}, clear=True)
        self.books_patch.start()
        self.addCleanup(self.books_patch.stop)
        self.env_patch = patch.dict(os.environ, {"NOVEL_WORKBENCH_DATA": str(self.data)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def create(self, stage="final", **extra):
        response = self.client.post("/api/local/books/test/tasks", json={"chapter": 2, "stage": stage, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def report(self, task, verdict="pass"):
        response = self.client.post(f"/api/local/tasks/{task['id']}/reports", json={
            "reviewer": "测试审阅人", "verdict": verdict, "content": "这是测试报告，只针对临时测试副本，不是真实章节的审查结论。"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_snapshots_reports_and_persistence_leave_book_unchanged(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*.md")}
        task = self.create(extra_paths=["设定/角色/主角.md"])
        self.assertIn("主角只知道现场的信息", task["packet"]["text"])
        self.report(task)
        with TestClient(app) as another_client:
            detail = another_client.get(f"/api/local/tasks/{task['id']}").json()
            self.assertEqual(detail["report_count"], 1)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*.md")})

    def test_final_requires_report_then_pass_then_author(self):
        task = self.create()
        endpoint = f"/api/local/tasks/{task['id']}/approve"
        self.assertEqual(self.client.post(endpoint, json={"report_id": 1}).status_code, 409)
        revised = self.report(task, "revise")
        self.assertFalse(revised["can_approve"])
        passed = self.report(task)
        report_id = passed["latest_report"]["id"]
        self.assertFalse(passed["approved"])
        self.assertTrue(passed["can_approve"])
        self.assertEqual(self.client.post(endpoint, json={"report_id": report_id - 1}).status_code, 409)
        approved = self.client.post(endpoint, json={"report_id": report_id}).json()
        self.assertTrue(approved["approved"])
        self.assertFalse(self.report(task, "revise")["approved"])

    def test_source_edit_invalidates_approval_and_shows_diff(self):
        task = self.report(self.create())
        self.client.post(f"/api/local/tasks/{task['id']}/approve", json={"report_id": task["latest_report"]["id"]})
        (self.root / "正文/第002章_接续.md").write_text("第二章正文已修改。\n", encoding="utf-8")
        detail = self.client.get(f"/api/local/tasks/{task['id']}").json()
        self.assertTrue(detail["stale"])
        self.assertFalse(detail["approved"])
        self.assertFalse(detail["can_approve"])
        changes = self.client.get(f"/api/local/tasks/{task['id']}/changes").json()
        self.assertIn("+第二章正文已修改。", changes["diffs"][0]["diff"])
        self.assertIn("第二章正文。", detail["packet"]["text"])

    def test_rule_and_parent_project_changes_are_tracked(self):
        (self.root / "AGENTS.md").unlink()
        parent_agents = self.root.parent / "AGENTS.md"
        parent_agents.write_text("父级项目约定。", encoding="utf-8")
        task = self.create()
        self.assertIn("父级项目约定", task["packet"]["text"])
        parent_agents.write_text("父级规则已经改变。", encoding="utf-8")
        self.assertTrue(self.client.get(f"/api/local/tasks/{task['id']}").json()["stale"])

    def test_new_ambiguous_chapter_file_invalidates_snapshot(self):
        task = self.create()
        (self.root / "正文/第002章_另一个版本.md").write_text("另一个版本。", encoding="utf-8")
        detail = self.client.get(f"/api/local/tasks/{task['id']}").json()
        self.assertTrue(detail["stale"])
        self.assertEqual(self.client.post("/api/local/books/test/tasks", json={"chapter":2,"stage":"final"}).status_code,409)

    def test_final_blind_read_hides_prior_reports_until_own_report(self):
        self.report(self.create("review"), "revise")
        final = self.create()
        endpoint = f"/api/local/tasks/{final['id']}/previous-reports"
        self.assertEqual(self.client.get(endpoint).status_code, 409)
        self.assertNotIn("这是测试报告", final["packet"]["text"])
        self.report(final)
        self.assertEqual(len(self.client.get(endpoint).json()), 1)

    def test_unlisted_manuscripts_require_explicit_version_choice(self):
        (self.root / "正文/阅读入口.md").write_text("[第一章](第001章_开篇.md)", encoding="utf-8")
        response = self.client.post("/api/local/books/test/tasks", json={"chapter":2,"stage":"final"})
        self.assertEqual(response.status_code,409)
        task = self.create(confirm_versions=True)
        self.assertTrue(task["packet"]["confirmed_versions"])

    def test_future_outline_allowed_but_draft_requires_previous_manuscript(self):
        response = self.client.post("/api/local/books/test/tasks", json={"chapter":4,"stage":"outline"})
        self.assertEqual(response.status_code,200,response.text)
        response = self.client.post("/api/local/books/test/tasks", json={"chapter":4,"stage":"draft"})
        self.assertEqual(response.status_code,409)

    def test_traversal_foreign_origin_and_bad_stage_rejected(self):
        self.assertEqual(self.client.get("/api/local/books/test/document",params={"path":"../AGENTS.md"}).status_code,404)
        self.assertEqual(self.client.post("/api/local/books/test/tasks",json={"chapter":2,"stage":"final","extra_paths":["../AGENTS.md"]}).status_code,404)
        self.assertEqual(self.client.post("/api/local/books/test/tasks",json={"chapter":2,"stage":"bogus"}).status_code,422)
        self.assertEqual(self.client.post("/api/local/books/test/tasks",headers={"Origin":"https://unrelated.example"},json={"chapter":2,"stage":"final"}).status_code,403)

    def test_non_final_cannot_approve_and_missing_rule_cannot_create(self):
        task = self.report(self.create("review"))
        self.assertFalse(task["can_approve"])
        self.assertEqual(self.client.post(f"/api/local/tasks/{task['id']}/approve",json={"report_id":task["latest_report"]["id"]}).status_code,409)
        (self.root / "写作规范/文风规则.md").unlink()
        self.assertEqual(self.client.post("/api/local/books/test/tasks",json={"chapter":2,"stage":"final"}).status_code,409)


if __name__ == "__main__":
    unittest.main()

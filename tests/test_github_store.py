"""
Тести для aggregator/github_store.py.

Тут НЕ ходимо в інтернет — передаємо власний, вигаданий "session" із
заздалегідь заготовленими відповідями (у тому самому форматі, що й
`requests`), і перевіряємо лише логіку навколо кодування/декодування
та обробки помилок.
"""

import base64
import json
import unittest

from aggregator.github_store import (
    GitHubStoreError, delete_json, read_json, trigger_workflow, write_json,
)


class _FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_body = json_body
        self.text = text or json.dumps(json_body or {})

    def json(self):
        return self._json_body


class _FakeSession:
    def __init__(self, get=None, put=None, delete=None, post=None):
        self._get = get
        self._put = put
        self._delete = delete
        self._post = post
        self.last_put_payload = None
        self.last_delete_payload = None
        self.last_post_payload = None
        self.last_post_url = None

    def get(self, url, headers=None, timeout=None):
        return self._get(url, headers)

    def put(self, url, headers=None, json=None, timeout=None):
        self.last_put_payload = json
        return self._put(url, headers, json)

    def delete(self, url, headers=None, json=None, timeout=None):
        self.last_delete_payload = json
        return self._delete(url, headers, json)

    def post(self, url, headers=None, json=None, timeout=None):
        self.last_post_payload = json
        self.last_post_url = url
        return self._post(url, headers, json)


class ReadJsonTests(unittest.TestCase):
    def test_missing_file_returns_none_none(self):
        session = _FakeSession(get=lambda url, headers: _FakeResponse(404))
        data, sha = read_json("me/repo", "tok", "profiles/x.json", session=session)
        self.assertIsNone(data)
        self.assertIsNone(sha)

    def test_existing_file_decodes_base64_json(self):
        payload = {"interval_hours": 3, "notify_email": "a@b.com"}
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        session = _FakeSession(
            get=lambda url, headers: _FakeResponse(200, {"content": encoded, "sha": "abc123"})
        )
        data, sha = read_json("me/repo", "tok", "profiles/x.json", session=session)
        self.assertEqual(data, payload)
        self.assertEqual(sha, "abc123")

    def test_server_error_raises(self):
        session = _FakeSession(get=lambda url, headers: _FakeResponse(403, text="no access"))
        with self.assertRaises(GitHubStoreError):
            read_json("me/repo", "tok", "profiles/x.json", session=session)


class WriteJsonTests(unittest.TestCase):
    def test_new_file_omits_sha(self):
        session = _FakeSession(put=lambda url, headers, body: _FakeResponse(201))
        write_json("me/repo", "tok", "profiles/x.json", {"a": 1}, "створено", session=session)
        self.assertNotIn("sha", session.last_put_payload)
        decoded = json.loads(base64.b64decode(session.last_put_payload["content"]))
        self.assertEqual(decoded, {"a": 1})

    def test_update_includes_sha(self):
        session = _FakeSession(put=lambda url, headers, body: _FakeResponse(200))
        write_json("me/repo", "tok", "profiles/x.json", {"a": 2}, "оновлено", sha="oldsha", session=session)
        self.assertEqual(session.last_put_payload["sha"], "oldsha")

    def test_error_raises(self):
        session = _FakeSession(put=lambda url, headers, body: _FakeResponse(422, text="bad sha"))
        with self.assertRaises(GitHubStoreError):
            write_json("me/repo", "tok", "profiles/x.json", {"a": 1}, "msg", session=session)


class DeleteJsonTests(unittest.TestCase):
    def test_success(self):
        session = _FakeSession(delete=lambda url, headers, body: _FakeResponse(200))
        delete_json("me/repo", "tok", "profiles/x.json", "sha1", "видалено", session=session)
        self.assertEqual(session.last_delete_payload["sha"], "sha1")

    def test_error_raises(self):
        session = _FakeSession(delete=lambda url, headers, body: _FakeResponse(404, text="not found"))
        with self.assertRaises(GitHubStoreError):
            delete_json("me/repo", "tok", "profiles/x.json", "sha1", "msg", session=session)


class TriggerWorkflowTests(unittest.TestCase):
    def test_success_posts_to_dispatches_endpoint_with_ref(self):
        session = _FakeSession(post=lambda url, headers, body: _FakeResponse(204))
        trigger_workflow("me/repo", "tok", "check.yml", ref="main", session=session)
        self.assertEqual(
            session.last_post_url,
            "https://api.github.com/repos/me/repo/actions/workflows/check.yml/dispatches",
        )
        self.assertEqual(session.last_post_payload, {"ref": "main"})

    def test_missing_actions_permission_raises(self):
        session = _FakeSession(post=lambda url, headers, body: _FakeResponse(403, text="no access"))
        with self.assertRaises(GitHubStoreError):
            trigger_workflow("me/repo", "tok", "check.yml", session=session)


if __name__ == "__main__":
    unittest.main()

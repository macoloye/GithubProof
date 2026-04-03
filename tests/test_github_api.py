from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from profile_audit.github_api import GitHubClient


class _FakeHeaders:
    def __init__(self, content_type: str = "application/json") -> None:
        self._content_type = content_type

    def get(self, key: str, default=None):
        if key.lower() == "content-type":
            return self._content_type
        return default


class _FakeResponse:
    def __init__(self, body: str, content_type: str = "application/json") -> None:
        self._body = body
        self.headers = _FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class GitHubApiTests(unittest.TestCase):
    def test_empty_response_returns_empty_list(self):
        client = GitHubClient(token="dummy")
        with patch("profile_audit.github_api.urlopen", return_value=_FakeResponse("")):
            self.assertEqual(client._request("GET", "/users/demo"), [])

    def test_non_json_response_raises_readable_error(self):
        client = GitHubClient(token="dummy")
        with patch("profile_audit.github_api.urlopen", return_value=_FakeResponse("<html>oops</html>", content_type="text/html")):
            with self.assertRaises(RuntimeError) as ctx:
                client._request("GET", "/users/demo")
        self.assertIn("non-JSON content", str(ctx.exception))

    def test_json_response_still_parses(self):
        client = GitHubClient(token="dummy")
        payload = {"login": "demo"}
        with patch("profile_audit.github_api.urlopen", return_value=_FakeResponse(json.dumps(payload))):
            self.assertEqual(client._request("GET", "/users/demo"), payload)


if __name__ == "__main__":
    unittest.main()

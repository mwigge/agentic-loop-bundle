#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "loopctl", ROOT / "runtime" / "loopctl.py"
)
assert SPEC and SPEC.loader
loopctl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = loopctl
SPEC.loader.exec_module(loopctl)


class Response(io.BytesIO):
    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> int:
    issue = {
        "fields": {
            "summary": "Parser guard",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Reject malformed input."}
                        ],
                    }
                ],
            },
        }
    }
    environment = {
        "JIRA_BASE_URL": "https://example.atlassian.net",
        "JIRA_EMAIL": "developer@example.com",
        "JIRA_API_TOKEN": "secret",
    }
    requests = []

    def urlopen(request: object, timeout: int = 0) -> Response:
        requests.append((request, timeout))
        if getattr(request, "method", "GET") == "POST":
            return Response(b'{"id":"1"}')
        return Response(json.dumps(issue).encode())

    with (
        mock.patch.dict(os.environ, environment, clear=False),
        mock.patch("urllib.request.urlopen", side_effect=urlopen),
    ):
        text = loopctl.jira_issue_text("ENG-123")
        assert "Parser guard" in text
        assert "Reject malformed input." in text
        loopctl.jira_comment("ENG-123", "Loop started")

    assert len(requests) == 2
    assert requests[0][0].full_url.endswith(
        "/rest/api/3/issue/ENG-123?fields=summary,description"
    )
    assert requests[1][0].full_url.endswith("/rest/api/3/issue/ENG-123/comment")
    print("Jira adapter tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

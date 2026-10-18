import copy
import io
import json
import socket
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from temporalio.exceptions import ApplicationError
from sqlalchemy import select

from backend.app.domain import HttpConfig, Graph, validate_graph
from backend.app import http_node as http, activities
from backend.app.templates import templates, node, edge
from backend.app.store import db, NodeRun, Attempt

HEAD = {"X-Flowforge-Client": "studio"}


class Response(io.BytesIO):
    def __init__(
        self, data=b'[{"name":"Ada"}]', status=200, content_type="application/json"
    ):
        super().__init__(data)
        self.status, self.content_type = status, content_type

    def getheader(self, name, default=""):
        return self.content_type if name == "Content-Type" else default


@pytest.fixture
def transport(monkeypatch):
    state = {"response": Response(), "requests": [], "closed": False}

    class Connection:
        sock = None

        def __init__(self, host, port, ip, timeout):
            state["address"] = (host, port, ip)

        def request(self, method, target, body=None, headers=None):
            state["requests"].append((method, target, body, headers))
            if state.get("error"):
                raise state["error"]

        def getresponse(self):
            return state["response"]

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(http, "resolve_public", lambda *args: "93.184.216.34")
    monkeypatch.setattr(http, "PinnedHTTP", Connection)
    monkeypatch.setattr(http, "PinnedHTTPS", Connection)
    return state


def run(config=None, inputs=None):
    return http.request_json(
        HttpConfig(**(config or {})).model_dump(), inputs or [], "run:node"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "http://localhost/x",
        "http://127.0.0.1",
        "http://[::1]",
        "http://10.1.1.1",
        "http://169.254.169.254",
        "http://user:password@example.com",
        "https://example.com:8080",
        "https://example.com/#x",
        "https://example.com\r\nX: value",
        "http://example.com\\@localhost/",
    ],
)
def test_invalid_urls_rejected(url):
    with pytest.raises(ValidationError):
        HttpConfig(url=url)


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "secret"},
        {"Host": "localhost"},
        {"Cookie": "secret"},
        {"X-Test": "a\r\nb"},
        {"Content-Length": "0"},
        {"Idempotency-Key": "custom"},
    ],
)
def test_reserved_or_injected_headers_rejected(headers):
    with pytest.raises(ValidationError):
        HttpConfig(headers=headers)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.2",
        "169.254.169.254",
        "::ffff:127.0.0.1",
        "224.0.0.1",
        "2002:0a00:0001::1",
    ],
)
def test_dns_private_addresses_rejected(monkeypatch, ip):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (ip, 443))]
    )
    with pytest.raises(ValueError, match="özel"):
        http.resolve_public("public.example", 443)


def test_mixed_dns_answer_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (None, None, None, None, ("93.184.216.34", 443)),
            (None, None, None, None, ("10.0.0.1", 443)),
        ],
    )
    with pytest.raises(ValueError):
        http.resolve_public("mixed.example", 443)


def test_pinned_transport_does_not_resolve_host_again(monkeypatch):
    calls = []
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda address, timeout: calls.append(address) or object(),
    )
    connection = http.PinnedHTTP("api.example", 80, "93.184.216.34", 5)
    connection.connect()
    assert calls == [("93.184.216.34", 80)]


def test_get_records_and_metadata(transport):
    out, port = run({"url": "https://api.example/users?limit=2"})
    assert out["records"] == [{"name": "Ada"}]
    assert out["meta"]["http"]["status"] == 200
    assert out["meta"]["count"] == 1 and port == "out"
    assert transport["address"] == ("api.example", 443, "93.184.216.34")
    assert transport["requests"][0][1] == "/users?limit=2"
    assert transport["closed"]


def test_nested_response_path(transport):
    transport["response"] = Response(b'{"data":{"items":[{"id":2}]}}')
    assert run({"responsePath": "data.items"})[0]["records"] == [{"id": 2}]


def test_post_uses_input_records_and_stable_idempotency_key(transport):
    out, _ = run({"method": "POST"}, [{"records": [{"id": 3}]}])
    method, _, body, headers = transport["requests"][0]
    assert method == "POST" and json.loads(body) == [{"id": 3}]
    assert headers["Idempotency-Key"] == "run:node"
    assert out["meta"]["inputCount"] == 1


def test_post_custom_body(transport):
    run({"method": "POST", "bodySource": "json", "body": {"title": "Test"}})
    assert json.loads(transport["requests"][0][2]) == {"title": "Test"}


def test_token_read_at_runtime_and_not_in_output(transport, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_HTTP_TOKEN_CRM", "private-secret-value")
    out, _ = run({"tokenEnv": "CRM"})
    assert transport["requests"][0][3]["Authorization"] == "Bearer private-secret-value"
    assert "private-secret-value" not in json.dumps(out)


def test_token_requires_https(transport, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_HTTP_TOKEN_CRM", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        run({"url": "http://api.example", "tokenEnv": "CRM"})
    assert not transport["requests"]


def test_missing_token(transport):
    with pytest.raises(ValueError, match="ortam"):
        run({"tokenEnv": "UNCONFIGURED_TEST"})


@pytest.mark.parametrize(
    "status,kind",
    [
        (302, ValueError),
        (400, ValueError),
        (401, ValueError),
        (429, OSError),
        (503, OSError),
    ],
)
def test_status_failure_and_retry_classification(transport, status, kind):
    transport["response"] = Response(b"secret-response-body", status=status)
    with pytest.raises(kind, match=f"HTTP {status}") as exc:
        run()
    assert "secret-response-body" not in str(exc.value)
    assert len(transport["requests"]) == 1


def test_post_network_failure_never_automatically_retried(transport):
    transport["error"] = OSError("secret-url-or-token")
    with pytest.raises(ValueError, match="POST otomatik") as exc:
        run({"method": "POST"})
    assert "secret-url-or-token" not in str(exc.value)


@pytest.mark.parametrize(
    "data", [b"not-json", b"[1,2]", b"null", b'{"n":NaN}', b'{"n":1e999}']
)
def test_invalid_response_rejected(transport, data):
    transport["response"] = Response(data)
    with pytest.raises(ValueError):
        run()


def test_missing_response_path(transport):
    with pytest.raises(ValueError, match="alan yolu"):
        run({"responsePath": "data.items"})


def test_response_size_limit(transport):
    transport["response"] = Response(b"x" * (http.MAX_RESPONSE + 1))
    with pytest.raises(ValueError, match="1 MB"):
        run()


def test_non_json_content_type(transport):
    transport["response"] = Response(b"<html>error</html>", content_type="text/html")
    with pytest.raises(ValueError, match="Content-Type"):
        run()


def test_timeout_is_sanitized_and_connection_closed(transport):
    transport["error"] = socket.timeout("sensitive-host")
    with pytest.raises(OSError, match="zaman aşımı") as exc:
        run()
    assert "sensitive-host" not in str(exc.value)
    assert transport["closed"]


def test_post_503_is_permanent(transport):
    transport["response"] = Response(status=503)
    with pytest.raises(ValueError, match="HTTP 503"):
        run({"method": "POST"})


def test_https_verifies_original_hostname(monkeypatch):
    calls = []
    sock = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout: sock)
    context = SimpleNamespace(
        wrap_socket=lambda stream, server_hostname: calls.append(server_hostname)
        or stream
    )
    monkeypatch.setattr(http.ssl, "create_default_context", lambda: context)
    http.PinnedHTTPS("api.example", 443, "93.184.216.34", 5).connect()
    assert calls == ["api.example"]


def test_record_count_limit():
    with pytest.raises(ValueError, match="10.000"):
        http.response_records([{}] * 10001, "")


def test_request_body_limit_before_network(transport):
    with pytest.raises(ValueError, match="1 MB"):
        run(
            {
                "method": "POST",
                "bodySource": "json",
                "body": {"x": "a" * http.MAX_REQUEST},
            }
        )
    assert not transport["requests"]


@pytest.mark.parametrize(
    "method,exception", [("GET", OSError), ("POST", ApplicationError)]
)
def test_activity_retry_classification(
    client, monkeypatch, transport, method, exception
):
    graph = copy.deepcopy(templates()[-1]["graph"])
    next(n for n in graph["nodes"] if n["id"] == "http")["config"]["method"] = method
    flow = client.post("/api/workflows", json=graph, headers=HEAD).json()
    result = client.post(
        f'/api/workflows/{flow["id"]}/runs',
        json={"revision": 1},
        headers={**HEAD, "Idempotency-Key": uuid.uuid4().hex},
    ).json()
    rid = result["id"]
    monkeypatch.setattr(activities.activity, "info", lambda: SimpleNamespace(attempt=1))
    activities.execute_node({"runId": rid, "nodeId": "source", "parents": []})
    transport["error"] = OSError("private detail")
    with pytest.raises(exception) as error:
        activities.execute_node({"runId": rid, "nodeId": "http", "parents": ["source"]})
    if method == "POST":
        assert error.value.non_retryable
    with db() as s:
        attempt = s.execute(
            select(Attempt).where(Attempt.run_id == rid, Attempt.node_id == "http")
        ).scalar_one()
        assert attempt.status == "failed" and "private detail" not in attempt.error


def test_http_graph_activity_output_reaches_report(client, monkeypatch, transport):
    graph = {
        "schemaVersion": 1,
        "name": "HTTP regression",
        "nodes": [
            node("source", "manual_input", "Start", 0, 0, records=[]),
            node("http", "http_request", "Fetch", 300, 0),
            node("report", "report", "Report", 600, 0),
        ],
        "edges": [edge("source", "http"), edge("http", "report")],
    }
    validate_graph(Graph(**graph))
    flow = client.post("/api/workflows", json=graph, headers=HEAD).json()
    result = client.post(
        f'/api/workflows/{flow["id"]}/runs',
        json={"revision": 1},
        headers={**HEAD, "Idempotency-Key": uuid.uuid4().hex},
    ).json()
    rid = result["id"]
    monkeypatch.setattr(activities.activity, "info", lambda: SimpleNamespace(attempt=1))
    for name, parents in [("source", []), ("http", ["source"]), ("report", ["http"])]:
        activities.execute_node({"runId": rid, "nodeId": name, "parents": parents})
    with db() as s:
        record = s.execute(
            select(NodeRun).where(NodeRun.run_id == rid, NodeRun.node_id == "report")
        ).scalar_one()
        assert activities.output_of(record)["records"] == [{"name": "Ada"}]
    # A completed activity replay returns the saved output without repeating the remote request.
    activities.execute_node({"runId": rid, "nodeId": "http", "parents": ["source"]})
    assert len(transport["requests"]) == 1

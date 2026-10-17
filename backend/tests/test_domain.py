import copy, json, pytest
from pydantic import ValidationError
from backend.app.domain import Graph, validate_graph, registry, compare, CONFIGS
from backend.app.templates import templates, node, edge, SAMPLE
from backend.app.operations import process, report_bytes


@pytest.mark.parametrize("t", templates())
def test_template_valid(t):
    assert validate_graph(Graph(**t["graph"]))


def test_unique_registry():
    r = registry()
    assert len(r) == 7
    assert len({d["type"] for d in r}) == 7


@pytest.mark.parametrize(
    "mutation",
    [
        "cycle",
        "self",
        "unknown",
        "duplicate_node",
        "duplicate_edge",
        "bad_port",
        "bad_target",
        "disconnected",
        "second_input",
        "no_report",
    ],
)
def test_invalid_graph(mutation):
    g = copy.deepcopy(templates()[0]["graph"])
    if mutation == "cycle":
        g["edges"].append(edge("report", "source"))
    elif mutation == "self":
        g["edges"].append(edge("clean", "clean"))
    elif mutation == "unknown":
        g["nodes"][0]["type"] = "arbitrary_python"
    elif mutation == "duplicate_node":
        g["nodes"].append(copy.deepcopy(g["nodes"][0]))
    elif mutation == "duplicate_edge":
        g["edges"].append(copy.deepcopy(g["edges"][0]))
    elif mutation == "bad_port":
        g["edges"][0]["sourceHandle"] = "bad"
    elif mutation == "bad_target":
        g["edges"][0]["target"] = "missing"
    elif mutation == "disconnected":
        g["nodes"].append(node("orphan", "transform", "orphan", 0, 0))
    elif mutation == "second_input":
        g["nodes"].append(node("input2", "manual_input", "input2", 0, 0))
    elif mutation == "no_report":
        g["nodes"] = [n for n in g["nodes"] if n["type"] != "report"]
        g["edges"] = [e for e in g["edges"] if e["target"] not in ["report", "empty"]]
    with pytest.raises((ValueError, ValidationError)):
        validate_graph(Graph(**g))


@pytest.mark.parametrize(
    "a,op,b,expected",
    [
        (2, "gt", 1, True),
        (2, "lt", 1, False),
        ("2", "gte", 2, True),
        ("A", "eq", "A", True),
        ("A", "ne", "B", True),
        ("Merhaba", "contains", "MER", True),
        (None, "gt", 0, False),
        ("nan", "gt", 0, False),
    ],
)
def test_comparison(a, op, b, expected):
    assert compare(a, op, b) == expected


def config(kind, **patch):
    return {**CONFIGS[kind]().model_dump(), **patch}


def test_clean_does_not_mutate_input():
    source = {"records": copy.deepcopy(SAMPLE), "meta": {}}
    original = copy.deepcopy(source)
    value, _ = process(
        "transform", config("transform", requiredField="email"), [source]
    )
    assert len(value["records"]) == 5
    assert source == original


@pytest.mark.parametrize(
    "op,amount,expected", [("gt", 1000, 4), ("lt", 1000, 2), ("eq", 1200, 2)]
)
def test_filters(op, amount, expected):
    value, _ = process(
        "transform",
        config(
            "transform",
            deduplicate=False,
            filterField="amount",
            filterOp=op,
            filterValue=amount,
        ),
        [{"records": SAMPLE}],
    )
    assert len(value["records"]) == expected


def test_projection_and_rename():
    v, _ = process(
        "transform",
        config("transform", selectFields=["name"], rename={"name": "person"}),
        [{"records": [{"name": " Ada ", "x": 3}]}],
    )
    assert v["records"] == [{"person": "Ada"}]


def test_merge_stable():
    v, _ = process(
        "merge", config("merge"), [{"records": [{"id": 2}]}, {"records": [{"id": 1}]}]
    )
    assert v["records"] == [{"id": 2}, {"id": 1}]


def test_merge_deduplicates():
    v, _ = process(
        "merge",
        config("merge", deduplicate=True),
        [{"records": [{"x": 1}]}, {"records": [{"x": 1}]}],
    )
    assert len(v["records"]) == 1


@pytest.mark.parametrize("size,port", [(0, "false"), (1, "true")])
def test_condition(size, port):
    _, p = process(
        "condition",
        config("condition"),
        [{"records": [{"id": i} for i in range(size)]}],
    )
    assert p == port


@pytest.mark.parametrize("operation,value", [("count", 2), ("sum", 30), ("mean", 15)])
def test_aggregate(operation, value):
    v, _ = process(
        "aggregate",
        config("aggregate", operation=operation),
        [
            {
                "records": [
                    {"category": "A", "amount": 10},
                    {"category": "A", "amount": 20},
                ]
            }
        ],
    )
    assert v["records"][0]["value"] == value


def test_report_escapes_html():
    content = report_bytes(
        {"records": [{"x": "<script>alert(1)</script>"}]}, "<img onerror=x>", "html"
    ).decode()
    assert "<script>" not in content
    assert "&lt;script&gt;" in content
    assert "<img" not in content


@pytest.mark.parametrize("value", ["=SUM(A1)", "+cmd", "-formula", "@x", "  =1"])
def test_csv_formula_safety(value):
    assert (
        "'" + value in report_bytes({"records": [{"x": value}]}, "test", "csv").decode()
    )


def test_json_unicode_roundtrip():
    assert (
        json.loads(report_bytes({"records": [{"ad": "Özdemir"}]}, "test", "json"))[
            "records"
        ][0]["ad"]
        == "Özdemir"
    )


def test_non_finite_record_rejected():
    g = copy.deepcopy(templates()[0]["graph"])
    g["nodes"][0]["config"]["records"] = [{"amount": float("nan")}]
    with pytest.raises(ValidationError):
        Graph(**g)


def test_graph_hash_does_not_depend_on_key_order():
    g = Graph(**templates()[0]["graph"])
    assert (
        Graph(**json.loads(json.dumps(g.model_dump(), sort_keys=True))).digest()
        == g.digest()
    )


@pytest.mark.parametrize("seconds", [-1, 301])
def test_delay_limits(seconds):
    with pytest.raises(ValidationError):
        CONFIGS["delay"](seconds=seconds)

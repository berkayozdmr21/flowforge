from __future__ import annotations
import json, hashlib, math
from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(Strict):
    x: float = 0
    y: float = 0


class CleanConfig(Strict):
    trim: bool = True
    removeEmpty: bool = True
    deduplicate: bool = True
    requiredField: str = Field(default="", max_length=100)
    filterField: str = Field(default="", max_length=100)
    filterOp: Literal["none", "eq", "ne", "gt", "gte", "lt", "lte", "contains"] = "none"
    filterValue: Any = None
    selectFields: list[str] = Field(default_factory=list, max_length=50)
    rename: dict[str, str] = Field(default_factory=dict, max_length=50)


class InputConfig(Strict):
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)


class ConditionConfig(Strict):
    field: str = Field(default="records.count", max_length=100)
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"] = "gt"
    value: Any = 0


class MergeConfig(Strict):
    deduplicate: bool = False


class ReportConfig(Strict):
    title: str = Field(default="Akış raporu", min_length=1, max_length=100)
    formats: list[Literal["json", "csv", "html"]] = Field(
        default_factory=lambda: ["json", "csv", "html"], min_length=1, max_length=3
    )


class DelayConfig(Strict):
    seconds: float = Field(default=3, ge=0.1, le=300)


class AggregateConfig(Strict):
    groupBy: str = Field(default="category", min_length=1, max_length=100)
    valueField: str = Field(default="amount", max_length=100)
    operation: Literal["count", "sum", "mean"] = "sum"


CONFIGS = {
    "manual_input": InputConfig,
    "transform": CleanConfig,
    "condition": ConditionConfig,
    "merge": MergeConfig,
    "report": ReportConfig,
    "delay": DelayConfig,
    "aggregate": AggregateConfig,
}
INFO = [
    (
        "manual_input",
        "Veri girişi",
        "Tetikleyici",
        "JSON kayıtlarıyla başla.",
        "Database",
        "#71895d",
    ),
    (
        "transform",
        "Veriyi düzenle",
        "Veri işleme",
        "Temizle, filtrele ve alanları dönüştür.",
        "WandSparkles",
        "#648b78",
    ),
    (
        "condition",
        "Koşul",
        "Kontrol",
        "Akışı bir koşula göre yönlendir.",
        "GitBranch",
        "#b28d55",
    ),
    (
        "merge",
        "Birleştir",
        "Kontrol",
        "Paralel yolları tek çıktıda topla.",
        "Combine",
        "#6a8897",
    ),
    (
        "report",
        "Rapor oluştur",
        "Çıktı",
        "JSON, CSV ve HTML çıktıları üret.",
        "FileBarChart",
        "#b88468",
    ),
    (
        "delay",
        "Bekle",
        "Kontrol",
        "İptal edilebilir kalıcı zamanlayıcı.",
        "Timer",
        "#8b8e6b",
    ),
    (
        "aggregate",
        "Özetle",
        "Veri işleme",
        "Grupla, say ve toplamları hesapla.",
        "ChartNoAxesCombined",
        "#71968e",
    ),
]


def registry():
    return [
        dict(
            type=t,
            title=title,
            category=cat,
            description=desc,
            icon=icon,
            color=color,
            version=1,
            configSchema=CONFIGS[t].model_json_schema(),
            defaults=CONFIGS[t]().model_dump(),
            inputs=[] if t == "manual_input" else ["in"],
            outputs=(
                []
                if t == "report"
                else ["true", "false"] if t == "condition" else ["out"]
            ),
        )
        for t, title, cat, desc, icon, color in INFO
    ]


class Node(Strict):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    type: str
    typeVersion: Literal[1] = 1
    label: str = Field(default="", max_length=80)
    position: Position = Field(default_factory=Position)
    config: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def known(self):
        if self.type not in CONFIGS:
            raise ValueError("Bilinmeyen blok türü.")
        self.config = CONFIGS[self.type](**self.config).model_dump()
        return self


class Edge(Strict):
    id: str = Field(min_length=1, max_length=100)
    source: str
    target: str
    sourceHandle: str = "out"
    targetHandle: Literal["in"] = "in"


class Graph(Strict):
    schemaVersion: Literal[1] = 1
    name: str = Field(default="İsimsiz akış", min_length=1, max_length=100)
    nodes: list[Node] = Field(min_length=1, max_length=100)
    edges: list[Edge] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def finite_json(self):
        try:
            json.dumps(self.model_dump(), allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Kayıtlar geçerli, sonlu JSON değerleri içermeli.")
        return self

    def digest(self):
        return hashlib.sha256(
            json.dumps(
                self.model_dump(),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()


def validate_graph(graph: Graph):
    ids = [n.id for n in graph.nodes]
    by = {n.id: n for n in graph.nodes}
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("Blok kimlikleri benzersiz olmalı.")
    if len({e.id for e in graph.edges}) != len(graph.edges):
        errors.append("Bağlantı kimlikleri benzersiz olmalı.")
    entries = [n.id for n in graph.nodes if n.type == "manual_input"]
    if len(entries) != 1:
        errors.append("Akışta tam olarak bir veri girişi olmalı.")
    incoming = {i: [] for i in ids}
    outgoing = {i: [] for i in ids}
    seen = set()
    for e in graph.edges:
        if e.source not in by or e.target not in by:
            errors.append("Bağlantıda bulunamayan blok var.")
            continue
        if e.source == e.target:
            errors.append("Bir blok kendisine bağlanamaz.")
        allowed = (
            []
            if by[e.source].type == "report"
            else ["true", "false"] if by[e.source].type == "condition" else ["out"]
        )
        if e.sourceHandle not in allowed:
            errors.append("Geçersiz çıkış portu: " + e.source)
        if by[e.target].type == "manual_input":
            errors.append("Veri girişine bağlantı yapılamaz.")
        key = (e.source, e.sourceHandle, e.target, e.targetHandle)
        if key in seen:
            errors.append("Aynı bağlantı iki kez eklenemez.")
        seen.add(key)
        incoming[e.target].append(e)
        outgoing[e.source].append(e)
    for n in graph.nodes:
        if n.type not in ["manual_input", "merge"] and len(incoming[n.id]) != 1:
            errors.append((n.label or n.id) + ": tam bir giriş bağlantısı gerekli.")
        if n.type == "merge" and len(incoming[n.id]) < 2:
            errors.append((n.label or n.id) + ": en az iki bağlantı gerekli.")
        if n.type not in ["report"] and not outgoing[n.id]:
            errors.append((n.label or n.id) + ": bir sonraki bloğa bağla.")
    degree = {i: len(incoming[i]) for i in ids}
    queue = [i for i in ids if degree[i] == 0]
    order = []
    while queue:
        i = queue.pop(0)
        order.append(i)
        for e in outgoing[i]:
            degree[e.target] -= 1
            if degree[e.target] == 0:
                queue.append(e.target)
    if len(order) != len(by):
        errors.append("Döngü tespit edildi. Akış yönlü ve döngüsüz olmalı.")
    if entries:
        visited = set()
        todo = [entries[0]]
        while todo:
            i = todo.pop()
            if i in visited:
                continue
            visited.add(i)
            todo.extend(e.target for e in outgoing[i])
        if visited != set(ids):
            errors.append("Bütün bloklar veri girişinden erişilebilir olmalı.")
    if not any(n.type == "report" for n in graph.nodes):
        errors.append("En az bir rapor bloğu gerekli.")
    if len(json.dumps(graph.model_dump(), ensure_ascii=False).encode()) > 1024 * 1024:
        errors.append("Akış belgesi 1 MB sınırını aşıyor.")
    if errors:
        raise ValueError("\n".join(dict.fromkeys(errors)))
    return order


def compare(a, op, b):
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if op == "contains":
        return str(b).casefold() in str(a).casefold()
    try:
        a, b = float(a), float(b)
        if not math.isfinite(a) or not math.isfinite(b):
            return False
    except (ValueError, TypeError):
        return False
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}.get(op, False)

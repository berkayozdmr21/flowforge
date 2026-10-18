from __future__ import annotations
import copy
from .domain import registry

SAMPLE = [
    {
        "name": " Ada ",
        "email": "ada@example.test",
        "amount": 1200,
        "category": "Tasarım",
    },
    {
        "name": "Berk",
        "email": "berk@example.test",
        "amount": 450,
        "category": "Geliştirme",
    },
    {
        "name": " Ada ",
        "email": "ada@example.test",
        "amount": 1200,
        "category": "Tasarım",
    },
    {"name": "  ", "email": "", "amount": None, "category": ""},
    {"name": "Cem", "email": "cem@example.test", "amount": 2100, "category": "Tasarım"},
    {
        "name": "Deniz",
        "email": "deniz@example.test",
        "amount": 780,
        "category": "Geliştirme",
    },
    {"name": "Ece", "email": "ece@example.test", "amount": 3200, "category": "Analiz"},
]
DEFAULTS = {x["type"]: x["defaults"] for x in registry()}


def node(id, type, label, x, y, **config):
    return dict(
        id=id,
        type=type,
        typeVersion=1,
        label=label,
        position={"x": x, "y": y},
        config={**copy.deepcopy(DEFAULTS[type]), **config},
    )


def edge(source, target, port="out"):
    return dict(
        id=source + "-" + port + "-" + target,
        source=source,
        target=target,
        sourceHandle=port,
        targetHandle="in",
    )


def templates():
    quality = {
        "schemaVersion": 1,
        "name": "Müşteri verisi · kalite kontrol",
        "nodes": [
            node("source", "manual_input", "Müşteri kayıtları", 40, 80, records=SAMPLE),
            node(
                "clean", "transform", "Veriyi temizle", 40, 340, requiredField="email"
            ),
            node(
                "report",
                "report",
                "Kalite raporu",
                400,
                210,
                title="Müşteri veri kalite raporu",
            ),
        ],
        "edges": [edge("source", "clean"), edge("clean", "report")],
    }
    threshold = {
        "schemaVersion": 1,
        "name": "Koşullu işlem · kol seçimi",
        "nodes": [
            node("source", "manual_input", "Örnek kayıtlar", 0, 200, records=SAMPLE),
            node("gate", "condition", "En az 3 kayıt?", 300, 200, value=3),
            node("yes", "transform", "Uygun kayıtlar", 600, 80, requiredField="email"),
            node("no", "transform", "Alternatif yol", 600, 340),
            node("merge", "merge", "Yolları birleştir", 900, 200),
            node("report", "report", "Sonuç raporu", 1200, 200),
        ],
        "edges": [
            edge("source", "gate"),
            edge("gate", "yes", "true"),
            edge("gate", "no", "false"),
            edge("yes", "merge"),
            edge("no", "merge"),
            edge("merge", "report"),
        ],
    }
    parallel = {
        "schemaVersion": 1,
        "name": "Satışlar · paralel analiz",
        "nodes": [
            node("source", "manual_input", "Satış kayıtları", 0, 200, records=SAMPLE),
            node(
                "high",
                "transform",
                "Yüksek tutarlı",
                310,
                50,
                filterField="amount",
                filterOp="gte",
                filterValue=1000,
                requiredField="email",
            ),
            node(
                "low",
                "transform",
                "Düşük tutarlı",
                310,
                350,
                filterField="amount",
                filterOp="lt",
                filterValue=1000,
                requiredField="email",
            ),
            node("merge", "merge", "Sonuçları birleştir", 640, 200),
            node(
                "report", "report", "Satış raporu", 960, 200, title="Satış segmentleri"
            ),
        ],
        "edges": [
            edge("source", "high"),
            edge("source", "low"),
            edge("high", "merge"),
            edge("low", "merge"),
            edge("merge", "report"),
        ],
    }
    http_template = dict(
        id="http-users",
        tag="HTTP ENTEGRASYONU",
        description="Genel bir API'den kullanıcıları al, alanları seç ve rapor indir. İnternet bağlantısı gerekir.",
        graph={
            "schemaVersion": 1,
            "name": "API kullanıcı raporu",
            "nodes": [
                node("source", "manual_input", "Manuel başlat", 0, 180, records=[]),
                node("http", "http_request", "Kullanıcıları getir", 310, 180),
                node(
                    "select",
                    "transform",
                    "Rapor alanları",
                    620,
                    180,
                    selectFields=["id", "name", "username", "email"],
                ),
                node(
                    "report",
                    "report",
                    "API raporu",
                    930,
                    180,
                    title="API kullanıcı raporu",
                ),
            ],
            "edges": [
                edge("source", "http"),
                edge("http", "select"),
                edge("select", "report"),
            ],
        },
    )
    return [
        dict(
            id="quality",
            tag="VERİ KALİTESİ",
            description="Tekrarları ve boş kayıtları temizle, koşula göre rapor üret.",
            graph=quality,
        ),
        dict(
            id="threshold",
            tag="AKILLI YÖNLENDİRME",
            description="Koşullu yolları ve atlanan blokları canlı izle.",
            graph=threshold,
        ),
        dict(
            id="parallel",
            tag="PARALEL İŞLEME",
            description="İki bağımsız veri kolunu aynı çalıştırmada birleştir.",
            graph=parallel,
        ),
        http_template,
    ]

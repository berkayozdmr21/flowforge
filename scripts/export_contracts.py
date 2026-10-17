import sys, json
from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.domain import Graph, registry
from backend.app.templates import templates

for name, value in [
    ("graph.schema.json", Graph.model_json_schema()),
    ("node-types.json", registry()),
]:
    (ROOT / "shared/schemas" / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
for t in templates():
    (ROOT / "examples" / (t["id"] + ".json")).write_text(
        json.dumps(t["graph"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
print("Shared contracts and three runnable example documents exported.")

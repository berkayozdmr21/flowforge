from __future__ import annotations
import json, copy, csv, io, html, hashlib, os, time
from pathlib import Path
from .domain import compare


def unique(rows):
    seen = set()
    out = []
    for row in rows:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def process(kind, config, inputs):
    records = copy.deepcopy(inputs[0]["records"] if inputs else [])
    if kind == "manual_input":
        records = copy.deepcopy(config["records"])
    elif kind == "transform":
        if config["trim"]:
            records = [
                {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
                for row in records
            ]
        if config["removeEmpty"]:
            records = [
                r for r in records if any(v is not None and v != "" for v in r.values())
            ]
        if config["requiredField"]:
            records = [
                r for r in records if r.get(config["requiredField"]) not in [None, ""]
            ]
        if config["deduplicate"]:
            records = unique(records)
        if config["filterOp"] != "none":
            records = [
                r
                for r in records
                if compare(
                    r.get(config["filterField"]),
                    config["filterOp"],
                    config["filterValue"],
                )
            ]
        if config["selectFields"]:
            records = [
                {k: r[k] for k in config["selectFields"] if k in r} for r in records
            ]
        if config["rename"]:
            records = [
                {config["rename"].get(k, k): v for k, v in r.items()} for r in records
            ]
    elif kind == "merge":
        records = [copy.deepcopy(row) for value in inputs for row in value["records"]]
        if config["deduplicate"]:
            records = unique(records)
    elif kind == "aggregate":
        groups = {}
        for row in records:
            key = json.dumps(
                row.get(config["groupBy"]), sort_keys=True, ensure_ascii=False
            )
            groups.setdefault(key, []).append(row)
        out = []
        for key, rows in groups.items():
            values = []
            for row in rows:
                try:
                    values.append(float(row[config["valueField"]]))
                except (KeyError, ValueError, TypeError):
                    pass
            result = (
                len(rows)
                if config["operation"] == "count"
                else (
                    sum(values)
                    if config["operation"] == "sum"
                    else sum(values) / len(values) if values else 0
                )
            )
            out.append(
                {
                    config["groupBy"]: json.loads(key),
                    "value": result,
                    "count": len(rows),
                }
            )
        records = out
    port = "out"
    meta = {"count": len(records), "inputCount": sum(len(x["records"]) for x in inputs)}
    if kind == "condition":
        value = (
            len(records)
            if config["field"] == "records.count"
            else records[0].get(config["field"]) if records else None
        )
        port = "true" if compare(value, config["op"], config["value"]) else "false"
        meta["decision"] = port
    return {"schemaVersion": 1, "records": records, "meta": meta}, port


def csv_cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.lstrip().startswith(
        ("=", "+", "-", "@", "\t", "\r")
    ):
        return "'" + value
    return "" if value is None else value


def report_bytes(envelope, title, fmt):
    rows = envelope["records"]
    columns = list(dict.fromkeys(k for row in rows for k in row))
    if fmt == "json":
        return json.dumps(
            envelope, ensure_ascii=False, indent=2, allow_nan=False
        ).encode("utf-8")
    if fmt == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([csv_cell(c) for c in columns])
        writer.writerows([[csv_cell(row.get(k)) for k in columns] for row in rows])
        return ("\ufeff" + output.getvalue()).encode("utf-8")
    head = "".join("<th>" + html.escape(str(c)) + "</th>" for c in columns)
    body = "".join(
        "<tr>"
        + "".join("<td>" + html.escape(str(row.get(c, ""))) + "</td>" for c in columns)
        + "</tr>"
        for row in rows
    )
    doc = (
        '<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'
        + html.escape(title)
        + "</title><style>body{font:15px system-ui;background:#f4f3f8;color:#242335;padding:40px}main{max-width:1100px;margin:auto;background:white;padding:32px;border-radius:16px}h1{font-size:32px}small{color:#777}table{border-collapse:collapse;width:100%;margin-top:24px}th,td{text-align:left;border-bottom:1px solid #e5e3ed;padding:12px;overflow-wrap:anywhere}th{background:#f0edf9}footer{margin-top:30px;color:#777;font-size:12px}</style><main><small>FLOWFORGE / EXECUTION REPORT</small><h1>"
        + html.escape(title)
        + "</h1><p>"
        + str(len(rows))
        + " kayıt · Kaydedilen akış çıktısı</p><table><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table><footer>FlowForge · Berkay Özdemir</footer></main></html>"
    )
    return doc.encode("utf-8")


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + os.urandom(8).hex() + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)

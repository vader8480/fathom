"""OpenAPI 3.1 description built from the server's route table (§5.14), and a
plain HTML reference page for ``/api/docs`` (no third-party JS)."""

from __future__ import annotations

import html
from typing import Any, Dict, Iterable, List, Tuple

_ERRORS = {
    "400": "Bad request", "401": "Authentication required", "403": "Forbidden (role or CSRF)", "404": "Not found",
    "405": "Method not allowed", "409": "Conflict (revision conflict, exists, v2_required, in_use)", "413": "Body too large",
    "415": "Unsupported format", "422": "Invalid (details.problems) or pdf_unsupported", "428": "Precondition required (If-Match / base_revision)",
    "429": "Throttled", "500": "Internal error (body has an error id only)",
}


def _group_end(p: str, i: int) -> int:
    """Index just past the ``)`` that closes the group opened at ``p[i] == "("``."""
    depth = 0
    j = i
    in_class = False
    while j < len(p):
        c = p[j]
        if c == "\\":
            j += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(p)


def _convert(p: str) -> Tuple[str, List[str]]:
    out: List[str] = []
    names: List[str] = []
    i = 0
    while i < len(p):
        c = p[i]
        if p.startswith("(?P<", i):
            end_name = p.index(">", i)
            name = p[i + 4:end_name]
            end = _group_end(p, i)
            names.append(name)
            out.append("{" + name + "}")
            i = end
            if i < len(p) and p[i] in "?*+":
                i += 1
            continue
        if p.startswith("(?:", i):
            end = _group_end(p, i)
            inner, inner_names = _convert(p[i + 3:end - 1])
            out.append(inner)
            names.extend(inner_names)
            i = end
            if i < len(p) and p[i] in "?*+":
                i += 1
            continue
        if c == "\\" and i + 1 < len(p):
            out.append(p[i + 1])
            i += 2
            continue
        if c in "^$":
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out), names


def path_of(pattern: str) -> str:
    """``/api/v2/projects/(?P<name>[^/]+)/history/(?P<rev>\\d+)`` → ``/api/v2/projects/{name}/history/{rev}``."""
    return _convert(pattern)[0]


def path_params(pattern: str) -> List[str]:
    return _convert(pattern)[1]


def _ref(name: str) -> Dict[str, Any]:
    return {"$ref": f"#/components/schemas/{name}"}


def _components() -> Dict[str, Any]:
    obj = {"type": "object", "additionalProperties": True}
    problem = {"type": "object", "required": ["level", "code", "ref", "path", "message"], "properties": {
        "level": {"type": "string", "enum": ["error", "warning"]}, "code": {"type": "string"}, "ref": {"type": "string"},
        "path": {"type": "string"}, "message": {"type": "string"}}}
    schemas: Dict[str, Any] = {
        "Doc": {"$ref": "v2/schema.json"},
        "Op": {"type": "object", "required": ["op"], "properties": {
            "op": {"type": "string", "enum": ["put", "merge", "del", "root", "move"]}, "coll": {"type": "string"}, "id": {"type": "string"},
            "key": {"type": "string", "enum": ["meta", "settings", "media"]}, "value": {}, "replace": {"type": "boolean"},
            "before": {"type": ["string", "null"]}}},
        "Problem": problem,
        "Hit": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["device", "port", "cable", "interface", "room", "rack", "floorplan", "attachment", "page"]},
            "id": {"type": "string"}, "device": {"type": ["string", "null"]}, "port": {"type": ["string", "null"]}, "title": {"type": "string"},
            "subtitle": {"type": "string"}, "room": {"type": "string"}, "score": {"type": "number"}, "match": {"type": "string"}}},
        "Answer": {"type": "object", "properties": {
            "question": {"type": "string"}, "intent": obj, "summary": {"type": "string"}, "paths": {"type": "array", "items": obj},
            "branch": obj, "suspects": {"type": "array", "items": obj}, "checks": {"type": "array", "items": obj},
            "notes": {"type": "array", "items": {"type": "string"}}, "suggestion": {"type": ["object", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]}, "unresolved": {"type": "array"}, "llm": obj}},
        "Error": {"type": "object", "required": ["error"], "properties": {
            "error": {"type": "string"}, "code": {"type": "string"}, "details": obj, "id": {"type": "string"}}},
        "Floorplan": obj, "Attachment": obj, "Import": obj,
        "User": {"type": "object", "properties": {
            "username": {"type": "string"}, "role": {"type": "string", "enum": ["viewer", "editor", "admin"]}, "disabled": {"type": "boolean"},
            "created": {"type": "string"}, "projects": obj, "password": {"type": "string", "writeOnly": True}}},
        "Login": {"type": "object", "required": ["username", "password"], "properties": {"username": {"type": "string"}, "password": {"type": "string", "writeOnly": True}}},
        "Scene": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "maxLength": 80}, "note": {"type": "string"},
                                                                     "copy_from": {"type": "string", "description": "scene id (or base) whose data seeds the new scene; default = current state"},
                                                                     "activate": {"type": "boolean", "default": False}}},
        "ScenePatch": {"type": "object", "properties": {"name": {"type": "string", "maxLength": 80}, "note": {"type": "string"}}},
        "Invite": {"type": "object", "properties": {"role": {"type": "string", "enum": ["viewer", "editor", "admin"], "default": "editor"},
                                                  "projects": {"type": "object", "additionalProperties": {"type": "string", "enum": ["viewer", "editor"]}, "description": "per-project role overrides"},
                                                  "ttl_hours": {"type": "integer", "minimum": 1, "maximum": 720, "default": 72}, "note": {"type": "string"}}},
        "PasswordChange": {"type": "object", "required": ["old", "new"], "properties": {"old": {"type": "string"}, "new": {"type": "string"}}},
        "ProjectCreate": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}, "template": {"type": "string"}, "org": {"type": "string"}}},
        "DocPut": {"type": "object", "required": ["doc"], "properties": {"doc": _ref("Doc"), "summary": {"type": "string"}, "base_revision": {"type": "integer"}}},
        "Changes": {"type": "object", "required": ["base_revision", "ops"], "properties": {
            "base_revision": {"type": "integer"}, "ops": {"type": "array", "items": _ref("Op"), "maxItems": 2000}, "summary": {"type": "string"}}},
        "Restore": {"type": "object", "required": ["base_revision"], "properties": {"base_revision": {"type": "integer"}}},
        "Share": {"type": "object", "properties": {"label": {"type": "string"}, "expires": {"type": "string"},
                                                  "scope": {"type": "string", "enum": ["all", "sop"], "default": "all",
                                                            "description": "all: whole viewer tree; sop: only /sop/… pages and the files they embed"}}},
        "Reconvert": {"type": "object", "properties": {"page": {"type": "integer"}, "hidden_layers": {"type": "array", "items": {"type": "string"}}}},
        "BuildOptions": {"type": "object", "properties": {"pdf": {"type": "boolean"}, "png": {"type": "boolean"},
                                                          "state": {"type": "string", "enum": ["all", "planned", "as_built", "everything"]},
                                                          "rooms": {"type": ["array", "null"], "items": {"type": "string"}},
                                                          "discovery": {"type": "boolean", "default": True, "description": "Include the Discovered connections report section (latest completed discovery run and promoted discovered cables)"}}},
        "Question": {"type": "object", "required": ["question"], "properties": {"question": {"type": "string"}, "room": {"type": "string"},
                                                                              "use_llm": {"type": "boolean"}, "history": {"type": "array"}}},
        "BackupCreate": {"type": "object", "properties": {"include_builds": {"type": "boolean"}, "label": {"type": "string"}}},
        "BackupRestore": {"type": "object", "required": ["confirm"], "properties": {"confirm": {"type": "string", "description": "the backup name"}}},
        "MergeRequest": {"type": "object", "required": ["survivor", "duplicates"], "properties": {
            "survivor": {"type": "string", "description": "id of the device that is kept"},
            "duplicates": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "ids merged into the survivor"},
            "choices": {"type": "object", "additionalProperties": {"type": "string"},
                        "description": "field key → device id whose value wins (or 'union' for list / text fields)"},
            "base_revision": {"type": "integer", "description": "merge only; defaults to the current revision"}}},
        "Template": obj, "V1Project": obj,
        "Page": {"type": "object", "required": ["title"], "properties": {
            "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,79}$"}, "title": {"type": "string"}, "parent": {"type": ["string", "null"]},
            "order": {"type": "integer"}, "kind": {"type": "string", "enum": ["sop", "troubleshooting", "checklist", "reference"]},
            "body": {"type": "string", "description": "Markdown (see fathom/markdown.py)"}, "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}}, "rooms": {"type": "array", "items": {"type": "string"}},
            "devices": {"type": "array", "items": {"type": "string"}}, "attachments": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string", "enum": ["draft", "published", "archived"]}, "owner": {"type": "string"},
            "review_due": {"type": "string"}, "base_revision": {"type": "integer"}}},
        "PagePreview": {"type": "object", "required": ["body"], "properties": {"body": {"type": "string"}}},
        "PageMove": {"type": "object", "properties": {"parent": {"type": ["string", "null"]}, "before": {"type": ["string", "null"]}, "order": {"type": "integer"}}},
        "ProblemReport": {"type": "object", "required": ["text"], "description": "JSON, or multipart/form-data with the same fields plus one image part (photo)",
                          "properties": {"text": {"type": "string", "maxLength": 2000}, "device": {"type": "string"}, "page": {"type": "string", "description": "page slug"},
                                         "name": {"type": "string", "description": "reporter name for anonymous reports"},
                                         "kind": {"type": "string", "enum": ["problem", "suggestion"], "default": "problem"},
                                         "device_status": {"type": "string", "enum": ["installed", "planned", "spare", "retired"], "description": "editor+: also set the device status"}}},
        "ProblemPatch": {"type": "object", "properties": {"status": {"type": "string", "enum": ["open", "resolved"]}, "note": {"type": "string"}}},
        "DiscoveryRun": {"type": "object", "properties": {
            "window": {"type": "integer", "minimum": 10, "maximum": 300, "description": "listen window in seconds (default from settings, 60)"},
            "probes": {"type": "array", "items": {"type": "string", "enum": ["unifi", "mdns", "lldp", "arp", "snmp", "yamaha", "videohub", "qsys", "ddm"]}, "description": "subset of the enabled probes"}}},
        "DiscoveryPromote": {"type": "object", "properties": {
            "entities": {"type": "array", "items": {"type": "string"}, "description": "entity ids to create as new devices"},
            "merge": {"type": "object", "additionalProperties": {"type": "string"}, "description": "entity id -> existing device id"},
            "templates": {"type": "object", "additionalProperties": {"type": "string"},
                          "description": "entity id -> library template id (an accepted model suggestion): new devices are set up from it like Add gear; merged devices get it when they have none"},
            "connections": {"type": "array", "items": {"type": "string"}, "description": "connection ids to add as cables"},
            "networks": {"type": "array", "items": {"type": "string"}},
            "ignore": {"type": "object", "properties": {"entities": {"type": "array", "items": {"type": "string"}}, "connections": {"type": "array", "items": {"type": "string"}},
                                                        "networks": {"type": "array", "items": {"type": "string"}}}},
            "unignore": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
            "room": {"type": "string"}}},
        "DiscoverySettings": {"type": "object", "properties": {
            "window": {"type": "integer"}, "room": {"type": "string"},
            "probes": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": True,
                                                                  "description": "per-probe fields (enabled, text / check / select values; list fields such as hosts as a string or array); "
                                                                                 "secrets: string sets, empty string clears, null keeps"}}}},
        "DiscoveryTest": {"type": "object", "required": ["probe"], "properties": {"probe": {"type": "string", "enum": ["unifi", "mdns", "lldp", "arp", "snmp", "yamaha", "videohub", "qsys", "ddm"]}, "settings": obj}},
    }
    return schemas


def build_spec(routes: Iterable[Any], version: str) -> Dict[str, Any]:
    """OpenAPI 3.1 dict with one ``paths`` entry per registered route."""
    schemas = _components()
    paths: Dict[str, Dict[str, Any]] = {}
    for rt in routes:
        method = str(getattr(rt, "method", "GET")).lower()
        pattern = str(getattr(rt, "pattern", ""))
        p, params = _convert(pattern)
        role = str(getattr(rt, "role", "viewer"))
        op: Dict[str, Any] = {
            "summary": getattr(rt, "summary", "") or "",
            "operationId": f"{method}_{getattr(getattr(rt, 'handler', None), '__name__', p.strip('/').replace('/', '_'))}",
            "tags": list(getattr(rt, "tags", []) or ["misc"]),
            "x-fathom-role": role,
        }
        if params:
            op["parameters"] = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}} for n in params]
        body = getattr(rt, "body", None)
        if body:
            if body == "Multipart":
                op["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
                    "type": "object", "properties": {"file": {"type": "array", "items": {"type": "string", "format": "binary"}}}}}}}
            elif body == "BackupZip":
                op["requestBody"] = {"required": True, "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
            else:
                op["requestBody"] = {"required": True, "content": {"application/json": {"schema": _ref(body) if body in schemas else {"type": "object"}}}}
        resp_name = getattr(rt, "response", None)
        ok_schema = _ref(resp_name) if resp_name and resp_name in schemas else {"type": "object"}
        responses: Dict[str, Any] = {"200": {"description": "OK", "content": {"application/json": {"schema": ok_schema}}}}
        if method == "post":
            responses["201"] = {"description": "Created"}
        if method == "delete":
            responses["204"] = {"description": "No content"}
        for code, desc in _ERRORS.items():
            responses[code] = {"description": desc, "content": {"application/json": {"schema": _ref("Error")}}}
        op["responses"] = responses
        if role != "public":
            op["security"] = [{"basic": []}, {"session": []}]
        paths.setdefault(p, {})[method] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "Fathom API", "version": version,
                 "description": "AVL documentation API. Mutating requests send X-Fathom: 1 (required for multipart / form / text bodies)."},
        "servers": [{"url": "./"}],
        "components": {
            "securitySchemes": {"basic": {"type": "http", "scheme": "basic"},
                                "session": {"type": "apiKey", "in": "cookie", "name": "fathom_session"}},
            "schemas": schemas,
        },
        "paths": paths,
    }


def render_docs(spec: Dict[str, Any]) -> str:
    """Endpoint table (method, path, role, summary) grouped by tag."""
    e = html.escape
    groups: Dict[str, List[Tuple[str, str, str, str]]] = {}
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            tag = (op.get("tags") or ["misc"])[0]
            groups.setdefault(tag, []).append((method.upper(), path, str(op.get("x-fathom-role", "")), str(op.get("summary", ""))))
    sections = []
    for tag in sorted(groups):
        rows = "".join(f"<tr><td><code>{e(m)}</code></td><td><code>{e(p)}</code></td><td>{e(r)}</td><td>{e(s)}</td></tr>"
                       for m, p, r, s in sorted(groups[tag], key=lambda t: (t[1], t[0])))
        sections.append(f'<h2 id="{e(tag)}">{e(tag)}</h2><table><thead><tr><th scope="col">Method</th><th scope="col">Path</th>'
                        f'<th scope="col">Role</th><th scope="col">Summary</th></tr></thead><tbody>{rows}</tbody></table>')
    info = spec.get("info", {})
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{e(info.get('title', 'API'))} {e(info.get('version', ''))}</title>"
            "<style>body{font:14px/1.45 system-ui,sans-serif;margin:24px;background:#0b1020;color:#e6eaf4}"
            "a{color:#8ea2ff}table{border-collapse:collapse;width:100%;margin-bottom:24px}"
            "td,th{border-bottom:1px solid rgba(255,255,255,.09);padding:4px 8px;text-align:left;vertical-align:top}"
            "th{color:#8e97ab;font-weight:600}code{font-size:13px}</style></head><body>"
            f"<h1>{e(info.get('title', 'API'))} <small>{e(info.get('version', ''))}</small></h1>"
            "<p>Machine-readable: <a href=\"openapi.json\">openapi.json</a> · doc schema: <a href=\"v2/schema.json\">v2/schema.json</a></p>"
            + "".join(sections) + "</body></html>")

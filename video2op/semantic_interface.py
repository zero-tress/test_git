"""Unbound interfaces for the current semantic schema; no controller or BT is selected."""
import json
from pathlib import Path

import yaml


def export(bundle, out):
    graph = bundle["semantic_graph"]
    steps = []
    for nid, node in graph["nodes"].items():
        if nid in {"START", "END"}:
            continue
        s = node["skill"]
        steps.append({"node_ref": nid, "operation": node["name"], "actor": s["X"],
                      "objects": s["O"], "start_guard": {"all": s["C_pre"]},
                      "completion_guard": {"all": s["C_post"]}, "invariants": s["C_const"],
                      "realization_candidates": s["R"], "selected_realization": None,
                      "binding_status": "unbound"})
    policy = {"schema_version": "semantic_execution_policy.v1", "graph_id": graph["graph_id"],
              "graph_schema": graph["schema_version"], "status": "unbound",
              "implementations": {}, "parameter_bindings": {}, "timeouts": {},
              "required_nodes": [s["node_ref"] for s in steps],
              "note": "接口线索，待执行侧绑定；未选择设备能力、行为子树或控制参数。"}
    program = {"schema_version": "semantic_program.v1", "graph_id": graph["graph_id"],
               "status": "unbound", "steps": steps, "relations": graph["relations"],
               "predicates": graph["predicates"], "runtime_detectors": {},
               "execution_verified": False}
    out = Path(out)
    (out / "execution_policy.yaml").write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
    (out / "program.json").write_text(json.dumps(program, ensure_ascii=False, indent=2) + "\n")


def validate_files(out):
    import jsonschema

    from .semantic import SCHEMA
    from .temporal_learning import validate_graph
    out = Path(out)
    result_path = out / "result.json"
    if result_path.exists():
        graph = json.loads(result_path.read_text())["semantic_graph"]
    else:
        graph = yaml.safe_load((out / "semantic_graph.yaml").read_text())  # historical read compatibility
    policy = yaml.safe_load((out / "execution_policy.yaml").read_text())
    program = json.loads((out / "program.json").read_text())
    errors = [e.message for e in jsonschema.Draft7Validator(yaml.safe_load(SCHEMA.read_text())).iter_errors(graph)]
    errors += validate_graph(graph)
    if policy.get("graph_id") != graph["graph_id"] or program.get("graph_id") != graph["graph_id"]:
        errors.append("interface graph identity mismatch")
    if policy.get("status") != "unbound" or program.get("status") != "unbound":
        errors.append("semantic interfaces must remain unbound")
    if policy.get("implementations") or policy.get("parameter_bindings") or program.get("execution_verified"):
        errors.append("unbound export cannot claim selected execution")
    expected = set(graph["nodes"]) - {"START", "END"}
    if {s["node_ref"] for s in program["steps"]} != expected or set(policy["required_nodes"]) != expected:
        errors.append("interface node references differ")
    return {"passed": not errors, "errors": errors, "nodes": len(expected),
            "validation_kind": "semantic_structure_and_unbound_interfaces", "execution_verified": False}

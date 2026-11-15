"""Keep grasp actions and complete goal-directed episodes as separate evidence units."""

from __future__ import annotations

from copy import deepcopy

from .cross_video_alignment import digest
from .knowledge import extract
from .task_causality import audit

PREPARATIONS = {"靠近", "打开", "清障"}


def build(bundle, source=None):
    graph = bundle["semantic_graph"]
    case = extract(bundle, source or bundle.get("source_analysis_path", ""))
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])}
    final_to_export = graph.get("x-meta", {}).get("final_to_export", {})
    causal = audit(bundle)
    bridges = {(r["from"], r["to"]): r for r in causal["edges"]}
    episodes = []
    for item in case["instances"]:
        if item["goal_key"] != "grasp_object":
            continue
        core_refs = set(item["atomic_refs"])
        target = item["target"]["local_entity"]
        anchors = {final_to_export[n] for n in item["source_node_refs"] if n in final_to_export}
        included = set(anchors)
        boundary_reasons = []
        changed = True
        while changed:
            changed = False
            for edge in graph["relations"]:
                source, destination = edge["from"], edge["to"]
                if destination not in included or source in included or source in {"START", "END"}:
                    continue
                node = graph["nodes"][source]
                if node["name"] not in PREPARATIONS or edge.get("basis") != "required_dependency":
                    continue
                labels = [graph["objects"][r]["label"] for r in node["skill"]["O"] if r in graph["objects"]]
                if target not in labels:
                    continue
                bridge = bridges.get((source, destination), {})
                if bridge.get("status") == "conflict":
                    continue
                included.add(source)
                changed = True
                boundary_reasons.append(
                    {
                        "source_node": source,
                        "prepares_node": destination,
                        "status": bridge.get("status", "needs_review"),
                        "membership": "candidate_preparation_not_proven_necessary",
                    }
                )
        refs = set(core_refs)
        state_requirements = []
        for nid in included:
            evidence = graph.get("evidence", {}).get(nid, {})
            if evidence.get("inferred") or evidence.get("already_satisfied"):
                state_requirements.append(
                    {
                        "node_ref": nid,
                        "name": graph["nodes"][nid]["name"],
                        "reason": "state_requirement_without_observed_event",
                    }
                )
                continue
            refs.update(evidence.get("atomic_refs", []))
        selected = [actions[r] for r in refs if r in actions and not actions[r].get("inferred")]
        milestone = [actions[r] for r in core_refs if r in actions]
        if not selected or not milestone:
            continue
        end = max(a["end"] for a in milestone)
        selected = [a for a in selected if a["start"] < end + 1e-6]
        refs = {a["id"] for a in selected}
        next_move = next(
            (
                a
                for a in sorted(actions.values(), key=lambda a: a["start"])
                if a["start"] >= end
                and a.get("object") == target
                and a.get("functional_role", {}).get("function") in {"带载移动", "移动"}
            ),
            None,
        )
        next_release = min(
            (
                a["start"]
                for a in actions.values()
                if a["start"] >= end
                and a.get("object") == target
                and a.get("functional_role", {}).get("function") == "释放"
            ),
            default=float(bundle["meta"]["duration"]),
        )
        verification_end = min(
            next_release,
            float(bundle["meta"]["duration"]),
            max(end + 1.0, min(next_move["end"], end + 3.0)) if next_move else end + 1.0,
        )
        episode = deepcopy(item)
        eid = "episode_" + digest([item["video_uid"], item["instance_id"], sorted(refs)])
        chosen_nodes = [n for n in bundle["task_nodes"]["task_nodes"] if set(n.get("atomic_refs", [])) & refs]
        node_ids = {n["id"] for n in chosen_nodes}
        episode.update(
            instance_id=eid,
            atomic_instance_ref=item["instance_id"],
            instance_scope="skill_episode",
            core_atomic_refs=sorted(core_refs),
            atomic_refs=sorted(refs),
            observed_process=sorted(selected, key=lambda a: (a["start"], str(a["id"]))),
            source_node_refs=[n["id"] for n in chosen_nodes],
            entity_context=deepcopy(bundle.get("semantic_scope", {}).get("objects", [])),
            boundary={
                "start_sec": min(a["start"] for a in selected),
                "end_sec": end,
                "context_end_sec": verification_end,
                "status": "graph_candidate_requires_video_review",
            },
            preparation_audit=boundary_reasons,
            state_requirements=state_requirements,
        )
        episode["operation_subgraph"] = {
            "nodes": [
                {
                    "node_id": n["id"],
                    "name": n["name"],
                    "selected_atomic_refs": [r for r in n.get("atomic_refs", []) if r in refs],
                    "partial_node": bool(set(n.get("atomic_refs", [])) - refs),
                    "semantic_preconditions": deepcopy(n.get("tuple", {}).get("C_pre", [])),
                    "semantic_postconditions": deepcopy(n.get("tuple", {}).get("C_post", [])),
                }
                for n in chosen_nodes
            ],
            "relations": [
                deepcopy(e) for e in bundle["operations"]["edges"] if e["from"] in node_ids and e["to"] in node_ids
            ],
        }
        episodes.append(episode)
    return {
        "schema_version": "skill_episodes.v1",
        "episodes": episodes,
        "task_causal_audit": causal,
        "policy": "Preparation range is separate from the atomic grasp and from verification context.",
    }


def export_clips(bundle, out, enabled=True):
    """Export whole processes separately; repeat exports verify existing bytes."""
    import json
    from pathlib import Path

    from .case_outputs import analysis_stamp, safe_name
    from .skill_clips import cut, save, sha256

    out = Path(out)
    folder = out / "clip/episodes"
    folder.mkdir(parents=True, exist_ok=True)
    episodes = json.loads((out / "skill_episodes.json").read_text())["episodes"]
    source = Path(bundle["meta"].get("path", ""))
    stamp = analysis_stamp(bundle)
    signature = digest(
        [
            bundle.get("source_video_sha256"),
            str(source),
            stamp,
            enabled,
            [(u["instance_id"], u["boundary"]) for u in episodes],
        ]
    )
    manifest = folder / "episode_sequence.json"
    if manifest.exists():
        prior = json.loads(manifest.read_text())
        if prior.get("input_fingerprint") != signature:
            raise ValueError("Episode export inputs changed; use a new analysis directory")
        for row in prior["episodes"]:
            for video in row["videos"]:
                if video["status"] == "exported" and sha256(folder / video["path"]) != video["probe"]["sha256"]:
                    raise ValueError("Episode clip bytes changed")
        return prior["episodes"]
    result = []
    available = source.is_file() and bundle["meta"].get("media_quality", {}).get("decoded_frames") != 0
    for n, unit in enumerate(episodes, 1):
        row = {
            "instance_id": unit["instance_id"],
            "atomic_instance_ref": unit["atomic_instance_ref"],
            "goal_key": unit["goal_key"],
            "boundary": unit["boundary"],
            "videos": [],
        }
        for kind, end in [
            ("process", unit["boundary"]["end_sec"]),
            ("verification_context", unit["boundary"]["context_end_sec"]),
        ]:
            name = f"{safe_name(source.stem)}_抓取过程{kind}_{n:03d}_{stamp}.mp4"
            target = folder / name
            if enabled and available:
                try:
                    info = cut(source, target, max(0, unit["boundary"]["start_sec"] - 0.25), end)
                    row["videos"].append(
                        {
                            "kind": kind,
                            "path": name,
                            "probe": info,
                            "status": "exported",
                            "source_start_sec": max(0, unit["boundary"]["start_sec"] - 0.25),
                            "source_end_sec": end,
                        }
                    )
                except Exception as exc:
                    row["videos"].append({"kind": kind, "path": name, "status": "failed", "error": str(exc)})
            else:
                row["videos"].append({"kind": kind, "path": name, "status": "disabled_or_unavailable"})
        result.append(row)
    save(
        manifest,
        {
            "schema_version": "skill_episode_clips.v1",
            "input_fingerprint": signature,
            "episodes": result,
            "policy": "The context video is verification evidence, not additional training trials.",
        },
    )
    return result

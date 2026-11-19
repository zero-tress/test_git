import json
import re
from copy import deepcopy

import pytest
from test_arm_hand_scope import example
from test_cross_video_generalization import instance, knowledge

from video2op import semantic
from video2op.single_video.case_outputs import chronology, export_case_clips, export_metadata, plan_clips, safe_name
from video2op.cross_video_delivery import export as export_cross
from video2op.single_video.pipeline import build_learning_graph
from video2op.skill_library import FIELDS, build, load


def case():
    b = example()
    build_learning_graph(b)
    return b


def test_shared_outline_has_all_seven_fields_and_reference_provenance():
    catalog, library = build()
    assert len(catalog["skill_index"]) == 10
    assert len(catalog["actions"]) == 14
    for t in library["templates"].values():
        assert set(t["seven_tuple"]) == set(FIELDS)
    grasp = library["templates"]["skill/GraspObjectSkill"]
    assert grasp["seven_tuple"]["C_pre"]
    assert grasp["seven_tuple"]["C_post"]
    assert grasp["seven_tuple"]["E"]["completion_checks"]
    assert grasp["seven_tuple"]["C_const"] == []
    assert all(r["observation_status"] == "not_observed" for r in grasp["seven_tuple"]["R"])


def test_human_demonstration_tuple_does_not_become_robot_world_fact(tmp_path):
    b = case()
    original = deepcopy(b["semantic_graph"]["nodes"]["N1"]["skill"]["X"])
    export_metadata(b, tmp_path)
    assert b["semantic_graph"]["nodes"]["N1"]["skill"]["X"] == original
    view = json.loads((tmp_path/"skill_instances.json").read_text())
    assert view["instances"][0]["seven_tuple"]["X"] == original
    assert "action_catalog" not in b["semantic_graph"]["x-meta"]


def test_new_case_has_shared_refs_and_no_per_video_catalog_or_removed_files(tmp_path):
    b = case()
    semantic.export(b, tmp_path)
    semantic.render(b, tmp_path)
    assert not any((tmp_path/n).exists() for n in ["report.html", "semantic_graph.yaml", "action_catalog.json"])
    assert (tmp_path/"result.json").is_file()
    assert (tmp_path/"workbench.html").is_file()
    view = json.loads((tmp_path/"skill_instances.json").read_text())
    assert (tmp_path/view["catalog_ref"]).resolve().is_file()
    assert (tmp_path/view["skill_templates_ref"]).resolve().is_file()
    for row in view["instances"]:
        assert set(row["seven_tuple"]) == set(FIELDS)
        assert row["template_ref"] in load()["templates"]


def test_grasp_acquire_level_difference_is_explicit():
    t = load()["templates"]["goal/acquire_object"]
    assert t["mapping_status"] == "requires_effect_alignment"
    assert any(e["predicate"] == "off_source_support" for e in t["seven_tuple"]["C_post"])
    assert t["unresolved"]


def test_context_overlap_is_not_misreported_as_action_parallelism():
    a = {"clip_id": "a", "action_start_sec": 0, "action_end_sec": 1,
         "source_start_sec": 0, "source_end_sec": 1.25}
    b = {"clip_id": "b", "action_start_sec": 1, "action_end_sec": 2,
         "source_start_sec": .75, "source_end_sec": 2.25}
    assert chronology([a,b])[0]["relation"] == "before"
    b["action_start_sec"] = .9
    assert chronology([a,b])[0]["relation"] == "overlap"


def test_state_only_or_inferred_opening_has_no_fabricated_clip():
    b = case()
    graph = b["semantic_graph"]
    nid = next(n for n,x in graph["nodes"].items() if x["name"] == "打开")
    graph["evidence"][nid]["already_satisfied"] = True
    plans, skipped = plan_clips(b, 10)
    assert nid not in {r["node_ref"] for r in plans}
    assert any(r["node_ref"] == nid for r in skipped)


def test_clip_filename_and_manifest_are_stable_and_keep_source_time(tmp_path, monkeypatch):
    from video2op.single_video import case_outputs
    b = case()
    source = tmp_path/"原视频.mp4"
    source.write_bytes(b"source evidence")
    b["meta"].update(path=str(source), duration=10, fps=30, analysis_time="2026-11-15T12:34:56.123456+08:00")
    b["meta"].pop("media_quality", None)
    export_metadata(b, tmp_path/"result")
    def cut(src, target, start, end):
        target.write_bytes(f"{start}-{end}".encode())
        return {"sha256": case_outputs.sha256(target), "duration": end-start, "decode_verified": True}
    monkeypatch.setattr(case_outputs, "cut", cut)
    index = export_case_clips(b, tmp_path/"result")
    assert index["status"] == "complete"
    assert index["exported"] > 0
    for n,row in enumerate(index["clips"],1):
        assert re.fullmatch(r"原视频_.+_\d{3}_20261115_123456_123456.mp4", row["filename"])
        assert row["sequence_index"] == n
        assert row["source_time_offset"] == row["source_start_sec"]
        assert (tmp_path/"result/clip"/row["filename"]).is_file()
    assert export_case_clips(b, tmp_path/"result") == index
    (tmp_path/"result/clip"/index["clips"][0]["filename"]).write_bytes(b"changed")
    with pytest.raises(ValueError,match="bytes differ"):
        export_case_clips(b, tmp_path/"result")


def test_clip_safety_does_not_write_an_inferred_skill_video(tmp_path):
    b = case()
    b["meta"].update(path=str(tmp_path/"missing.mp4"), duration=10)
    export_metadata(b, tmp_path/"result")
    index = export_case_clips(b, tmp_path/"result")
    assert index["status"] == "needs_review"
    assert index["exported"] == 0
    assert not list((tmp_path/"result/clip").glob("*.mp4"))


def test_cross_video_output_retains_seven_tuple_and_instance_bindings_outside_outline(tmp_path):
    k = knowledge([instance("a", ["靠近", "抓取"]),instance("b", ["靠近", "抓取"],target="另一盒子")])
    export_cross(k, tmp_path)
    view = json.loads((tmp_path/"skill_catalog.json").read_text())
    grasp = view["skills"][0]
    assert set(grasp["learned_seven_tuple"]) == set(FIELDS)
    assert "bindings" not in grasp["learned_seven_tuple"]["O"]
    assert len(grasp["instance_bindings"]) == 2
    assert grasp["instance_count"] == 2
    assert grasp["learned_seven_tuple"]["R"]
    assert not (tmp_path/"action_catalog.json").exists()


def test_safe_name_removes_windows_reserved_filename_characters():
    assert not re.search(r'[<>:"/\\|?*]',safe_name('A:B/C\\D*'))


def test_acquire_reference_method_switches_remain_in_R_without_becoming_observed():
    r = load()["templates"]["skill/AcquireObjectSkill"]["seven_tuple"]["R"]
    refs = {i["skill_template_ref"] for i in r}
    assert refs == {"skill/GraspObjectSkill", "skill/RetrieveObjectFromContainerSkill"}
    assert all(i["observation_status"] == "not_observed" for i in r)
    guarded = next(i for i in r if "guard" in i)
    assert guarded["guard"]["on_unknown"] == "stop_before_method"

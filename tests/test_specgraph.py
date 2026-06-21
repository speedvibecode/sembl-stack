from sembl_stack.artifacts import Bounds, Task
from sembl_stack.specgraph import build_spec_graph


def test_build_spec_graph_extracts_scope_and_concepts(tmp_path):
    spec_dir = tmp_path / "specs" / "001-feedback"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "\n".join([
            "# Feedback board",
            "Entity: feedback_item",
            "Route: POST /api/feedback",
            "Users must be authenticated before creating feedback.",
        ]),
        encoding="utf-8",
    )

    graph = build_spec_graph(
        Task(text="Build the feedback board", repo=str(tmp_path), spec_path=str(spec_dir)),
        Bounds(editable_paths=["src/app.py"], forbidden_areas=["infra/"]),
    )

    node_types = {node["type"] for node in graph.nodes}
    node_ids = {node["id"] for node in graph.nodes}

    assert "entity" in node_types
    assert "route" in node_types
    assert "data_rule" in node_types
    assert "scope:editable:src/app.py" in node_ids
    assert "scope:forbidden:infra/" in node_ids
    assert graph.data["schema_version"] == 1


def test_build_spec_graph_has_task_node_without_spec():
    graph = build_spec_graph(Task(text="Small task", repo="."))

    assert graph.nodes[0]["id"] == "task"
    assert graph.sources == ["task.text"]

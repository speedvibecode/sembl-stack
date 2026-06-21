import json

from sembl_stack.adapters.spec_sembl import SemblSpecAdapter
from sembl_stack.artifacts import Task


def test_fallback_bounds_json_accepts_utf8_bom(tmp_path):
    (tmp_path / "bounds.json").write_text(
        json.dumps({"editable_paths": ["src/"], "forbidden_areas": ["infra/"]}),
        encoding="utf-8-sig",
    )

    bounds = SemblSpecAdapter(transport="cli").plan(
        Task(text="t", repo=str(tmp_path), spec_path=None)
    )

    assert bounds.editable_paths == ["src/"]
    assert bounds.forbidden_areas == ["infra/"]

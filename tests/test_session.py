from sembl_stack.session import (STAGES, Session, load, resume_or_new, save, _path)


def test_session_roundtrips_through_disk(tmp_path):
    s = Session(repo=str(tmp_path), mode="existing", run_id="r1", current_stage="loop")
    save(s)
    back = load(str(tmp_path))
    assert back is not None
    assert back.repo == s.repo and back.mode == "existing"
    assert back.run_id == "r1" and back.current_stage == "loop"


def test_load_missing_is_none(tmp_path):
    assert load(str(tmp_path)) is None


def test_advance_marks_complete_and_moves_to_next(tmp_path):
    s = Session(repo=str(tmp_path))
    assert s.current_stage == STAGES[0]
    nxt = s.advance()
    assert nxt == STAGES[1]
    assert STAGES[0] in s.completed
    assert s.done is False


def test_advance_stops_at_last_stage_and_marks_done(tmp_path):
    s = Session(repo=str(tmp_path))
    for _ in range(len(STAGES) + 2):     # over-advance: must clamp at the last stage
        s.advance()
    assert s.current_stage == STAGES[-1]
    assert s.done is True


def test_resume_returns_saved_incomplete_session(tmp_path):
    s = Session(repo=str(tmp_path), mode="existing", current_stage="merge")
    s.completed = ["bounds", "loop", "verify"]
    save(s)
    resumed = resume_or_new(str(tmp_path))
    assert resumed.current_stage == "merge"
    assert resumed.completed == ["bounds", "loop", "verify"]


def test_resume_starts_fresh_when_none_or_complete(tmp_path):
    # no session file -> fresh
    fresh = resume_or_new(str(tmp_path))
    assert fresh.current_stage == STAGES[0]
    assert fresh.completed == []
    # a complete session -> also fresh (nothing to continue)
    done = Session(repo=str(tmp_path), completed=list(STAGES), current_stage=STAGES[-1])
    save(done)
    assert resume_or_new(str(tmp_path)).current_stage == STAGES[0]


def _write_session_file(tmp_path, text):
    p = _path(str(tmp_path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_load_returns_none_on_corrupt_json(tmp_path):
    """A truncated session.json must not brick bare `sembl-stack` — treat it as no session."""
    _write_session_file(tmp_path, '{"repo": "x", "current_stage": "loop"')   # truncated
    assert load(str(tmp_path)) is None
    # ...and the guided entry still starts fresh rather than raising.
    assert resume_or_new(str(tmp_path)).current_stage == STAGES[0]


def test_load_returns_none_on_unknown_stage(tmp_path):
    """An unknown current_stage would crash advance()'s STAGES.index — reject it at load."""
    _write_session_file(tmp_path, '{"repo": "x", "current_stage": "not-a-stage"}')
    assert load(str(tmp_path)) is None


def test_load_filters_unknown_completed_stages(tmp_path):
    _write_session_file(
        tmp_path,
        '{"repo": "x", "current_stage": "loop", "completed": ["bounds", "bogus"]}')
    s = load(str(tmp_path))
    assert s is not None
    assert s.completed == ["bounds"]            # bogus stage dropped, no crash

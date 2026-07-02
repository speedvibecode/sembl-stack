"""Pure onboarding helpers; Textual itself is exercised only in tests/local."""
from __future__ import annotations

import pytest

from sembl_stack import onboarding


def test_profile_for_api_key_stores_env_pointer_only():
    prof = onboarding.profile_for_runner(
        "api-key",
        key_env="ANTHROPIC_API_KEY",
        custom_key_env="",
    )
    assert prof.runner == "api-key"
    assert prof.executor == "claude"
    assert prof.key_source == "env:ANTHROPIC_API_KEY"


def test_custom_api_env_name_overrides_menu_choice():
    prof = onboarding.profile_for_runner(
        "api-key",
        key_env="ANTHROPIC_API_KEY",
        custom_key_env="MY_PROVIDER_KEY",
        executor="opencode",
        model="local/model",
        strict=False,
        preset="full-loop",
    )
    assert prof.key_source == "env:MY_PROVIDER_KEY"
    assert prof.executor == "opencode"
    assert prof.model == "local/model"
    assert prof.strict is False
    assert prof.preset == "full-loop"


def test_api_key_value_shape_is_rejected_as_env_name():
    with pytest.raises(ValueError, match="environment variable name"):
        onboarding.profile_for_runner(
            "api-key",
            key_env="ANTHROPIC_API_KEY",
            custom_key_env="sk-ant-secret-value",
        )


def test_mock_profile_has_no_key_source():
    prof = onboarding.profile_for_runner("mock")
    assert prof.runner == "mock"
    assert prof.executor == "mock"
    assert prof.key_source is None


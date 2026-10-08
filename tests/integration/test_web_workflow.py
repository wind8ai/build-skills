"""Compiled workflow descriptions cannot bypass the core execution contract."""

import copy

import pytest

from build_skills.web.workflow_schema import builtin_workflow, validate_description


def test_compiled_builtin_and_required_gates():
    description = builtin_workflow()
    assert len(description["nodes"]) == 11
    broken = copy.deepcopy(description)
    broken["nodes"] = [node for node in broken["nodes"] if node["id"] != "approve"]
    with pytest.raises(ValueError, match="confirmation"):
        validate_description(broken)
    broken = copy.deepcopy(description)
    broken["edges"][0]["target"] = "deliver"
    with pytest.raises(ValueError, match="contract"):
        validate_description(broken)
    broken = copy.deepcopy(description)
    broken["nodes"][0]["actions"].append("shell")
    with pytest.raises(ValueError, match="Unknown"):
        validate_description(broken)

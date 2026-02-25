"""Tests for Oracle V2 model changes."""
import pytest
from app.models import SubmissionStatus


def test_submission_status_has_gate_passed():
    assert SubmissionStatus.gate_passed == "gate_passed"


def test_submission_status_has_gate_failed():
    assert SubmissionStatus.gate_failed == "gate_failed"

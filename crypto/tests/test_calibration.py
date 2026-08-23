from __future__ import annotations

import pytest

from kquant_crypto.calibration import (
    PredictionRecord,
    calibration_report,
    fit_isotonic_calibrator,
    fit_platt_calibrator,
    model_evidence_gate,
)


def test_calibration_report_requires_oos_folds_and_beats_climatology():
    records = [
        PredictionRecord(0.00, 0, "fold-1"), PredictionRecord(0.00, 0, "fold-1"),
        PredictionRecord(1.00, 1, "fold-2"), PredictionRecord(1.00, 1, "fold-2"),
        PredictionRecord(0.00, 0, "fold-3"), PredictionRecord(1.00, 1, "fold-3"),
    ]
    result = calibration_report(records)
    assert result["fold_count"] == 3
    assert result["brier"] < result["climatology_brier"]
    assert result["gate"] == "passed"


def test_probability_cannot_pass_without_calibration_metadata():
    allowed, reasons = model_evidence_gate({"model_probability": 0.8, "calibration_gate_passed": False})
    assert allowed is False
    assert reasons == ["calibration_gate_closed"]


def test_probability_range_is_strict():
    with pytest.raises(ValueError):
        calibration_report([PredictionRecord(1.2, 1, "fold-1")])


def test_model_artifact_hash_mismatch_closes_evidence_gate():
    allowed, reasons = model_evidence_gate({
        "model_hash": "old",
        "expected_model_hash": "new",
        "feature_order_hash": "same",
        "expected_feature_order_hash": "same",
    })
    assert allowed is False
    assert reasons == ["model_hash_mismatch"]


def test_probability_calibrators_fit_only_with_sufficient_validation_rows():
    records = [
        PredictionRecord(0.05 + index * 0.045, 1 if index >= 10 else 0, "validation")
        for index in range(20)
    ]
    platt = fit_platt_calibrator(records)
    isotonic = fit_isotonic_calibrator(records)
    assert platt is not None
    assert isotonic is not None
    assert len(platt.predict([0.1, 0.5, 0.9])) == 3
    calibrated = isotonic.predict([0.1, 0.5, 0.9])
    assert calibrated == sorted(calibrated)
    assert fit_platt_calibrator(records[:19]) is None
    assert fit_isotonic_calibrator(records[:19]) is None

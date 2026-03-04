from pathlib import Path

from keylight.effect_verify import (
    EffectCandidate,
    EffectVerificationConfig,
    default_accepted_candidates,
    run_effect_verification,
    write_effect_verification_report,
)
from keylight.models import RgbColor


def test_default_accepted_candidates_count_and_values() -> None:
    candidates = default_accepted_candidates(pad_length=64)

    assert len(candidates) == 16
    assert all(candidate.pad_length == 64 for candidate in candidates)


def test_run_effect_verification_runs_matrix() -> None:
    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        if write_method == "output":
            return len(report_bytes)
        raise RuntimeError("feature blocked")

    config = EffectVerificationConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_sequence=[0, 1],
        color_sequence=[RgbColor(255, 0, 0)],
        candidates=[
            EffectCandidate(
                name="out",
                template="{report_id} {zone} {r} {g} {b}",
                write_method="output",
                report_id=1,
                pad_length=8,
            ),
            EffectCandidate(
                name="feat",
                template="{report_id} {zone} {r} {g} {b}",
                write_method="feature",
                report_id=1,
                pad_length=8,
            ),
        ],
        step_delay_ms=0,
        repeat=2,
    )
    report = run_effect_verification(config, writer=fake_writer)

    assert report.total_steps == 4
    assert report.success_count == 2
    assert [step.zone_index for step in report.steps] == [0, 1, 0, 1]


def test_run_effect_verification_max_steps_limits_output() -> None:
    config = EffectVerificationConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_sequence=[0],
        color_sequence=[RgbColor(255, 0, 0)],
        candidates=[
            EffectCandidate(
                name="out",
                template="{report_id} {zone} {r} {g} {b}",
                write_method="output",
                report_id=1,
                pad_length=8,
            )
        ],
        step_delay_ms=0,
        repeat=5,
        max_steps=2,
    )
    report = run_effect_verification(config, writer=lambda **_: 8)

    assert report.total_steps == 2
    assert report.success_count == 2


def test_write_effect_verification_report(tmp_path: Path) -> None:
    config = EffectVerificationConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_sequence=[0],
        color_sequence=[RgbColor(255, 0, 0)],
        candidates=[
            EffectCandidate(
                name="out",
                template="{report_id} {zone} {r} {g} {b}",
                write_method="output",
                report_id=1,
                pad_length=8,
            )
        ],
        step_delay_ms=0,
        repeat=1,
    )
    report = run_effect_verification(config, writer=lambda **_: 8)
    output_path = tmp_path / "effect_verify.json"

    returned = write_effect_verification_report(report, output_path)

    assert returned == output_path
    content = output_path.read_text(encoding="utf-8")
    assert "total_steps" in content


from pathlib import Path


SPEC_DIR = Path(__file__).parents[1] / "specs" / "flight-blender"


def test_flight_blender_contract_is_pinned() -> None:
    source_commit = (SPEC_DIR / "source-commit.txt").read_text().strip()
    digest = (SPEC_DIR / "specification.sha256").read_text().strip()
    specification = (SPEC_DIR / "specification.yaml").read_text()

    assert len(source_commit) == 40
    assert digest.startswith("d83a2b1")
    assert "/flight_declaration_ops/set_flight_declaration:" in specification
    assert "/flight_stream/set_telemetry:" in specification
    assert "flightblender.write" in specification

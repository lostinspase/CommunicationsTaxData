import json

from pypdf import PdfWriter
from sqlalchemy import select

from communications_tax_data.exemption_forms import catalog_exemption_forms
from communications_tax_data.models import ExemptionFormArtifact, ExemptionFormStateCheck


def test_catalog_uses_sanitized_manifest_and_tracks_state_checks(session, tmp_path):
    state_dir = tmp_path / "PA"
    state_dir.mkdir()
    pdf = state_dir / "exemptionforms_PA_REV-1220.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf.open("wb") as handle:
        writer.write(handle)

    manifest = {
        "retrievedAt": "2026-07-27T11:45:00.000Z",
        "stateChecks": [
            {
                "state": "PA",
                "stateName": "Pennsylvania",
                "listed": 1,
                "saved": 1,
                "status": "available",
                "notice": None,
                "sourcePage": "https://www.fastsalestax.com/forms/exemption",
            },
            {
                "state": "MS",
                "stateName": "Mississippi",
                "listed": 0,
                "saved": 0,
                "status": "source_anomaly",
                "notice": "Source notice requires manual review.",
                "sourcePage": "https://www.fastsalestax.com/forms/exemption",
            },
        ],
        "files": [
            {
                "state": "PA",
                "fileName": pdf.name,
                "title": "Pennsylvania Exemption Certificate",
                "formCode": "REV-1220",
                "revision": "07-2025",
                "officialUrl": "https://www.pa.gov/example",
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = catalog_exemption_forms(session, tmp_path)
    artifact = session.scalar(select(ExemptionFormArtifact))
    checks = {item.state_code: item for item in session.scalars(select(ExemptionFormStateCheck))}

    assert result["pdfs_seen"] == 1
    assert result["state_checks"] == 2
    assert result["source_anomalies"] == ["MS"]
    assert artifact.title == "Pennsylvania Exemption Certificate"
    assert artifact.form_number == "REV-1220"
    assert artifact.source_metadata["official_url"] == "https://www.pa.gov/example"
    assert checks["PA"].form_count == 1
    assert checks["MS"].status == "source_anomaly"

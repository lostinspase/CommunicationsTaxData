from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.models import (
    ExemptionFormArtifact,
    ExemptionFormStateCheck,
    utcnow,
)

FASTSALES_PAGE = "https://www.fastsalestax.com/forms/exemption"
STATE_FROM_NAME = re.compile(r"^exemptionforms_([A-Z]{2})_", re.IGNORECASE)


def _manifest(root: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    path = root / "manifest.json"
    if not path.is_file():
        return {}, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = {
        (str(item.get("state") or "").upper(), str(item.get("fileName") or "")): item
        for item in payload.get("files", [])
    }
    return files, payload


def _manifest_timestamp(payload: dict[str, Any]) -> datetime:
    raw = str(payload.get("retrievedAt") or "")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        return utcnow()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf_metadata(path: Path, *, extract_text: bool = True) -> tuple[str, str, dict[str, Any]]:
    fallback = path.stem.split("_", 2)[-1].replace("_", " ").strip()
    try:
        reader = PdfReader(path)
        document = reader.metadata or {}
        first_page = (
            (reader.pages[0].extract_text() or "")[:4000]
            if reader.pages and extract_text
            else ""
        )
        title = str(document.get("/Title") or "").strip() or fallback
        form_match = re.search(
            r"(?:Form|Certificate|ST[:\s-]*)([A-Z0-9][A-Z0-9 .:/_-]{1,35})",
            f"{fallback}\n{first_page}",
            re.IGNORECASE,
        )
        form_number = (form_match.group(1).strip() if form_match else fallback)[:100]
        metadata = {
            "original_filename": path.name,
            "page_count": len(reader.pages),
            "pdf_title": document.get("/Title"),
            "pdf_author": document.get("/Author"),
            "pdf_creation_date": str(document.get("/CreationDate") or "") or None,
        }
        return title[:500], form_number, metadata
    except Exception as exc:
        return (
            fallback[:500],
            fallback[:100],
            {
                "original_filename": path.name,
                "metadata_error": f"{type(exc).__name__}: {exc}",
            },
        )


def catalog_exemption_forms(
    session: Session,
    directory: Path,
    *,
    provider_code: str = "fastsalestax",
) -> dict[str, Any]:
    """Catalog downloaded PDFs without storing protected credentials or document bytes."""
    root = directory.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    manifest_files, manifest = _manifest(root)
    retrieved_at = _manifest_timestamp(manifest) if manifest else utcnow()
    existing = {
        item.source_url_sha256: item
        for item in session.scalars(
            select(ExemptionFormArtifact).where(
                ExemptionFormArtifact.provider_code == provider_code
            )
        )
    }
    counts: dict[str, Any] = {
        "provider": provider_code,
        "directory": str(root),
        "pdfs_seen": 0,
        "inserted": 0,
        "updated": 0,
        "states": set(),
        "state_checks": 0,
        "source_anomalies": [],
    }
    for path in sorted(root.rglob("*.pdf")):
        counts["pdfs_seen"] += 1
        state_match = STATE_FROM_NAME.match(path.name)
        parent_state = path.parent.name.upper()
        inferred_state = (
            state_match.group(1).upper()
            if state_match
            else (parent_state if re.fullmatch(r"[A-Z]{2}", parent_state) else None)
        )
        manifest_item = manifest_files.get((inferred_state or "", path.name), {})
        state_code = str(manifest_item.get("state") or inferred_state or "").upper() or None
        title, form_number, metadata = _pdf_metadata(
            path, extract_text=not bool(manifest_item)
        )
        if manifest_item:
            title = str(manifest_item.get("title") or title)[:500]
            form_number = str(manifest_item.get("formCode") or form_number)[:100]
            metadata.update(
                {
                    "official_url": manifest_item.get("officialUrl"),
                    "revision": manifest_item.get("revision"),
                    "manifest_filename": manifest_item.get("fileName"),
                }
            )
        relative_path = str(path.relative_to(root))
        source_key = hashlib.sha256(
            f"{provider_code}|{relative_path.casefold()}".encode()
        ).hexdigest()
        content_hash = _file_hash(path)
        item = existing.get(source_key)
        values = {
            "state_code": state_code,
            "jurisdiction_scope": "state" if state_code else "multistate",
            "form_type": "sales_use_exemption",
            "form_number": form_number,
            "title": title,
            "source_page_url": FASTSALES_PAGE,
            "download_url": f"authenticated-ui:{state_code or 'multistate'}/{path.name}",
            "local_path": relative_path,
            "mime_type": "application/pdf",
            "bytes_received": path.stat().st_size,
            "content_sha256": content_hash,
            "status": "downloaded",
            "source_metadata": metadata,
            "retrieved_at": retrieved_at,
            "last_verified_at": utcnow(),
        }
        if item is None:
            session.add(
                ExemptionFormArtifact(
                    provider_code=provider_code,
                    source_url_sha256=source_key,
                    **values,
                )
            )
            counts["inserted"] += 1
        else:
            changed = any(getattr(item, key) != value for key, value in values.items())
            for key, value in values.items():
                setattr(item, key, value)
            counts["updated"] += int(changed)
        if state_code:
            counts["states"].add(state_code)

    checked_on = retrieved_at.date() if manifest else date.today()
    for check in manifest.get("stateChecks", []):
        state_code = str(check.get("state") or "").upper()
        if not state_code:
            continue
        item = session.scalar(
            select(ExemptionFormStateCheck).where(
                ExemptionFormStateCheck.provider_code == provider_code,
                ExemptionFormStateCheck.state_code == state_code,
                ExemptionFormStateCheck.checked_on == checked_on,
            )
        )
        values = {
            "form_count": int(check.get("listed") or 0),
            "downloaded_count": int(check.get("saved") or 0),
            "status": str(check.get("status") or "missing"),
            "notice": check.get("notice"),
            "source_page_url": str(check.get("sourcePage") or FASTSALES_PAGE),
            "source_metadata": {"state_name": check.get("stateName")},
            "checked_at": retrieved_at,
        }
        if item is None:
            session.add(
                ExemptionFormStateCheck(
                    provider_code=provider_code,
                    state_code=state_code,
                    checked_on=checked_on,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(item, key, value)
        counts["state_checks"] += 1
        if values["status"] == "source_anomaly":
            counts["source_anomalies"].append(state_code)
    session.flush()
    counts["states"] = sorted(counts["states"])
    counts["state_count"] = len(counts["states"])
    return counts

import zipfile
from datetime import date

from communications_tax_data.models import SalesTaxZipRate
from communications_tax_data.sales_tax_file import import_sales_tax_zip_file


def test_basic_zip_rate_file_is_deduplicated_and_kept_as_candidate(session, tmp_path):
    archive = tmp_path / "AS_zip4_basic_07_26.zip"
    payload = (
        "ZIP_CODE\tSTATE_ABBREV\tCOUNTY_NAME\tCITY_NAME\tTOTAL_SALES_TAX\tTOTAL_USE_TAX\n"
        "12345\tTX\tTEST\tCITY A\t.082500\t.082500\n"
        "12345\tTX\tTEST\tCITY A\t.082500\t.082500\n"
        "12345\tTX\tTEST\tCITY B\t.062500\t.062500\n"
    )
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("AS_zip4_basic_07_26.txt", payload)

    result = import_sales_tax_zip_file(session, archive)
    rows = session.query(SalesTaxZipRate).order_by(SalesTaxZipRate.city_name).all()

    assert result["raw_rows"] == 3
    assert result["distinct_candidates"] == 2
    assert result["postal_codes"] == 1
    assert result["split_postal_codes"] == 1
    assert rows[0].occurrence_count == 2
    assert rows[0].release_date == rows[1].release_date == date(2026, 7, 1)
    assert "does not disclose the plus-four ranges" in rows[0].limitations

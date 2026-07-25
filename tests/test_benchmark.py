from communications_tax_data.benchmark import _signature as benchmark_signature
from communications_tax_data.comparison import _signature as comparison_signature


def test_tax_type_signature_normalizes_database_collation_variants():
    upper = {
        "tax_type": 18,
        "tax_level": 0,
        "tax_category": " CONNECTIVITY CHARGES ",
        "tax_description": "Federal Universal Service Fund",
    }
    lower = {
        "tax_type": 18,
        "tax_level": 0,
        "tax_category": "connectivity charges",
        "tax_description": "federal universal service fund",
    }

    assert benchmark_signature(upper) == benchmark_signature(lower)
    assert benchmark_signature(upper) == comparison_signature(
        upper["tax_type"],
        upper["tax_level"],
        upper["tax_category"],
        upper["tax_description"],
    )

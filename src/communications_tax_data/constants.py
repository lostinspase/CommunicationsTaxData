STATE_FIPS_TO_ABBR = {
    "01": "AL",
    "02": "AK",
    "04": "AZ",
    "05": "AR",
    "06": "CA",
    "08": "CO",
    "09": "CT",
    "10": "DE",
    "11": "DC",
    "12": "FL",
    "13": "GA",
    "15": "HI",
    "16": "ID",
    "17": "IL",
    "18": "IN",
    "19": "IA",
    "20": "KS",
    "21": "KY",
    "22": "LA",
    "23": "ME",
    "24": "MD",
    "25": "MA",
    "26": "MI",
    "27": "MN",
    "28": "MS",
    "29": "MO",
    "30": "MT",
    "31": "NE",
    "32": "NV",
    "33": "NH",
    "34": "NJ",
    "35": "NM",
    "36": "NY",
    "37": "NC",
    "38": "ND",
    "39": "OH",
    "40": "OK",
    "41": "OR",
    "42": "PA",
    "44": "RI",
    "45": "SC",
    "46": "SD",
    "47": "TN",
    "48": "TX",
    "49": "UT",
    "50": "VT",
    "51": "VA",
    "53": "WA",
    "54": "WV",
    "55": "WI",
    "56": "WY",
    "60": "AS",
    "66": "GU",
    "69": "MP",
    "72": "PR",
    "78": "VI",
}

STATE_ABBR_TO_FIPS = {value: key for key, value in STATE_FIPS_TO_ABBR.items()}


def sst_level(jurisdiction_type: str) -> int:
    """Map X12 DE 1721 codes used by SST into this project's 0-3 levels."""
    if jurisdiction_type == "45":
        return 1
    if jurisdiction_type == "00":
        return 2
    return 3


def sst_type_name(jurisdiction_type: str) -> str:
    return {
        "45": "state",
        "00": "county",
        "01": "city",
        "02": "town",
        "03": "village",
        "63": "special_taxing_district",
        "79": "special_taxing_district",
    }.get(jurisdiction_type, f"x12_{jurisdiction_type}")

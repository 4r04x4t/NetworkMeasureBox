"""Wi-Fi regulatory domains the box can use: the countries of the Linux wireless regulatory database.

Taken from wireless-regdb 2026.05.30 (Debian 13, /lib/firmware/regulatory.db on the box) with the DFS rule
set of each country (ETSI, FCC, JP, or none). The Web UI names the countries in its own language; "00" is the
world domain, the most restrictive one. Regenerate from a newer regulatory.db when the package changes.
"""
from typing import Dict, List, Optional

REGDB_VERSION = "2026.05.30"

# country code -> DFS rule set
REGDOMAINS: Dict[str, str] = {
    "AD": "ETSI", "AE": "FCC", "AF": "ETSI", "AI": "ETSI", "AL": "ETSI", "AM": "ETSI", "AN": "ETSI", "AR": "FCC",
    "AS": "FCC", "AT": "ETSI", "AU": "ETSI", "AW": "ETSI", "AZ": "ETSI", "BA": "ETSI", "BB": "FCC", "BD": "JP",
    "BE": "ETSI", "BF": "FCC", "BG": "ETSI", "BH": "ETSI", "BL": "ETSI", "BM": "FCC", "BN": "FCC", "BO": "JP",
    "BR": "FCC", "BS": "FCC", "BT": "ETSI", "BW": "ETSI", "BY": "ETSI", "BZ": "JP", "CA": "FCC", "CF": "FCC",
    "CH": "ETSI", "CI": "FCC", "CL": "JP", "CN": "FCC", "CO": "FCC", "CR": "FCC", "CU": "FCC", "CX": "FCC",
    "CY": "ETSI", "CZ": "ETSI", "DE": "ETSI", "DK": "ETSI", "DM": "FCC", "DO": "FCC", "DZ": "JP", "EC": "FCC",
    "EE": "ETSI", "EG": "ETSI", "ES": "ETSI", "ET": "ETSI", "FI": "ETSI", "FM": "FCC", "FO": "ETSI", "FR": "ETSI",
    "GB": "ETSI", "GD": "FCC", "GE": "ETSI", "GF": "ETSI", "GH": "FCC", "GI": "ETSI", "GL": "ETSI", "GP": "ETSI",
    "GR": "ETSI", "GT": "", "GU": "FCC", "GY": "", "HK": "ETSI", "HN": "FCC", "HR": "ETSI", "HT": "FCC",
    "HU": "ETSI", "ID": "", "IE": "ETSI", "IL": "ETSI", "IM": "ETSI", "IN": "", "IR": "ETSI", "IS": "ETSI",
    "IT": "ETSI", "JM": "FCC", "JO": "ETSI", "JP": "JP", "KE": "ETSI", "KH": "ETSI", "KN": "ETSI", "KP": "JP",
    "KR": "JP", "KW": "ETSI", "KY": "FCC", "KZ": "ETSI", "LB": "FCC", "LC": "ETSI", "LI": "ETSI", "LK": "ETSI",
    "LS": "ETSI", "LT": "ETSI", "LU": "ETSI", "LV": "ETSI", "MA": "ETSI", "MC": "ETSI", "MD": "ETSI", "ME": "ETSI",
    "MF": "ETSI", "MH": "FCC", "MK": "ETSI", "MN": "FCC", "MO": "FCC", "MP": "FCC", "MQ": "ETSI", "MR": "ETSI",
    "MT": "ETSI", "MU": "FCC", "MV": "ETSI", "MW": "ETSI", "MX": "FCC", "MY": "FCC", "NA": "ETSI", "NG": "ETSI",
    "NI": "FCC", "NL": "ETSI", "NO": "ETSI", "NP": "JP", "NZ": "ETSI", "OM": "ETSI", "PA": "FCC", "PE": "FCC",
    "PF": "ETSI", "PG": "FCC", "PH": "FCC", "PK": "", "PL": "ETSI", "PM": "ETSI", "PR": "FCC", "PT": "ETSI",
    "PW": "FCC", "PY": "FCC", "QA": "ETSI", "RE": "ETSI", "RO": "ETSI", "RS": "ETSI", "RU": "", "RW": "FCC",
    "SA": "ETSI", "SE": "ETSI", "SG": "FCC", "SI": "ETSI", "SK": "ETSI", "SM": "ETSI", "SN": "FCC", "SR": "ETSI",
    "SV": "FCC", "SX": "ETSI", "SY": "ETSI", "TC": "FCC", "TD": "ETSI", "TG": "ETSI", "TH": "FCC", "TN": "ETSI",
    "TR": "ETSI", "TT": "FCC", "TW": "FCC", "TZ": "ETSI", "UA": "ETSI", "UG": "FCC", "US": "FCC", "UY": "FCC",
    "UZ": "ETSI", "VA": "ETSI", "VC": "ETSI", "VE": "FCC", "VI": "FCC", "VN": "FCC", "VU": "FCC", "WF": "ETSI",
    "WS": "ETSI", "YE": "", "YT": "ETSI", "ZA": "ETSI", "ZW": "ETSI",
}


def normalize_country(value: object) -> Optional[str]:
    """"auto", "00" or a known country code (upper case); None for anything else."""
    code = str(value or "").strip().upper()
    if code == "AUTO":
        return "auto"
    if code == "00" or code in REGDOMAINS:
        return code
    return None


def country_choices() -> List[List[str]]:
    """[code, DFS rule set] for every country, for the Web UI's list (sorted there by the shown name)."""
    return [[code, dfs] for code, dfs in sorted(REGDOMAINS.items())]

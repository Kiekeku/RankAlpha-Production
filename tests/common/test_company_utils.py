from company_utils import clean_company_name


def test_clean_company_name_strips_common_suffixes():
    assert clean_company_name("Acme, Inc.") == "Acme"
    assert clean_company_name("Foo-Bar PLC") == "Foo-Bar"
    assert clean_company_name("Global Holdings PLC") == "Global"
    assert clean_company_name("Contoso LLC") == "Contoso"
    assert clean_company_name("Berkshire Hathaway Inc. Class A") == "Berkshire Hathaway"
    assert clean_company_name("Acme Class B") == "Acme"


def test_clean_company_name_handles_edge_cases():
    assert clean_company_name("Inc.") == "Inc."
    assert clean_company_name("  ") == ""
    assert clean_company_name(None) is None

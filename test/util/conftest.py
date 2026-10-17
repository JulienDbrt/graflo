import pytest


@pytest.fixture
def docs_simple():
    return [{"id": 0, "a": 2}, {"id": 0, "b": 1}]


@pytest.fixture
def docs_simple_two_doc():
    return [{"id": 0, "a": 2}, {"id": 1, "b": 1}]


@pytest.fixture()
def merge_input_no_disc():
    return [
        {"crossref": 501100022272, "doi": "10.13039/501100022272"},
        {
            "_key": "F4320337236",
            "country_code": "AU",
            "created_date": "2023-02-13",
            "display_name": "Graduate School of Health, University of Technology Sydney",
            "updated_date": "2023-06-09T19:18:16.597411",
        },
    ]


@pytest.fixture()
def merge_output_no_disc():
    return [
        {
            "crossref": 501100022272,
            "doi": "10.13039/501100022272",
            "_key": "F4320337236",
            "country_code": "AU",
            "created_date": "2023-02-13",
            "display_name": "Graduate School of Health, University of Technology Sydney",
            "updated_date": "2023-06-09T19:18:16.597411",
        }
    ]

import pytest
from dtcc_data import download_data

@pytest.fixture
def sample_list():
    return [1, 2, 3]

def test_length(sample_list):
    assert len(sample_list) == 3

def test_osm()
    bboxA = (319891.837881, 6399790.206438, 319891+2000, 6399790.206438+2000)
    download_data('footprints', 'OSM', bboxA)

import pytest

@pytest.fixture
def sample_list():
    return [1, 2, 3]

def test_length(sample_list):
    assert len(sample_list) == 3

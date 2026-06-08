import pytest

from hprc import MockLLMClient, HPRCConfig


@pytest.fixture
def mock_client():
    return MockLLMClient()


@pytest.fixture
def config(mock_client):
    return HPRCConfig(llm_client=mock_client)

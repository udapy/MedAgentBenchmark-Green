import sys
import os
import yaml
import pytest

# Ensure root and src are in path
sys.path.append(os.path.abspath("."))
sys.path.append(os.path.abspath("src"))

from src.agent import Agent

def test_config_loading():
    """Verifies that the Agent class loads configuration correctly."""
    
    # Ensure config file exists
    config_path = "config/agent.config.yaml"
    assert os.path.exists(config_path), "Config file not found"
    
    # Instantiate Agent
    agent = Agent()
    
    # Check if config is loaded
    assert agent.config is not None
    assert "agent" in agent.config
    assert agent.config["agent"]["name"] == "MedAgentBench Assessor"
    
    # Check FHIR URL priority (should be config value since env var not set in this test process, or default)
    # in config/agent.config.yaml: base_url: "http://fhir-server:8080/fhir"
    # in agent.py logic: env > config > default
    
    # If we don't set env var, it should be the config value
    if "FHIR_BASE_URL" in os.environ:
        del os.environ["FHIR_BASE_URL"]
        
    # Re-init to clear any previous state
    agent = Agent()
    expected_url = "http://fhir-server:8080/fhir"
    assert agent.fhir_base_url == expected_url, f"Expected {expected_url}, got {agent.fhir_base_url}"

if __name__ == "__main__":
    test_config_loading()
    print("Config loading test PASSED")

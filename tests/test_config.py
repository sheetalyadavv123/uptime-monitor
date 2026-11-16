# =============================================================================
# tests/test_config.py  -  SAFETY CHECKS FOR SETTINGS
# =============================================================================
import pytest

from app.config import INSECURE_DEFAULT_SECRET, Settings


# Test: development may use the default secret.
def test_development_may_use_the_default_secret():
    Settings(environment="development", secret_key=INSECURE_DEFAULT_SECRET).check_is_safe_to_run()


# Test: production refuses the default secret.
def test_production_refuses_the_default_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(environment="production", secret_key=INSECURE_DEFAULT_SECRET).check_is_safe_to_run()


# Test: production refuses a short secret.
def test_production_refuses_a_short_secret():
    with pytest.raises(RuntimeError, match="too short"):
        Settings(environment="production", secret_key="short").check_is_safe_to_run()


# Test: production accepts a long secret.
def test_production_accepts_a_long_secret():
    Settings(environment="production", secret_key="x" * 40).check_is_safe_to_run()


# Test: settings are read from environment variables.
def test_settings_are_read_from_environment_variables(monkeypatch):
    monkeypatch.setenv("WORKER_COUNT", "9")
    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")
    settings = Settings()
    assert settings.worker_count == 9  # the text "9" became the number 9
    assert settings.allow_private_urls is True

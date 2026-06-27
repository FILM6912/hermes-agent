from app.core.onboarding_gate import onboarding_client_allowed

class TestOnboardingGate:
    def test_loopback_allowed(self):
        assert onboarding_client_allowed(client_host="127.0.0.1")

    def test_public_ip_blocked(self):
        assert not onboarding_client_allowed(client_host="8.8.8.8")

    def test_open_env_bypasses_check(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_ONBOARDING_OPEN", "1")
        assert onboarding_client_allowed(client_host="8.8.8.8")

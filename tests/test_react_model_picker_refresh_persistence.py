"""React model picker must keep in-page selection across catalog refresh (legacy ui.js parity)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
USE_AGENT_MODELS = (REPO / "frontend/src/features/chat/hooks/useAgentModels.ts").read_text(
    encoding="utf-8"
)
MODEL_SELECTION = (REPO / "frontend/src/features/chat/modelSelection.ts").read_text(
    encoding="utf-8"
)
CHAT_INTERFACE = (REPO / "frontend/src/features/chat/components/ChatInterface.tsx").read_text(
    encoding="utf-8"
)


def test_reconcile_preserves_in_page_selection_when_model_still_in_catalog():
    assert "currentInCatalog && !preferBootDefault" in MODEL_SELECTION
    assert "nextConfig: null" in MODEL_SELECTION


def test_use_agent_models_uses_reconcile_not_blind_default_overwrite():
    assert "reconcileModelSelection" in USE_AGENT_MODELS
    assert "preferBootDefault" in USE_AGENT_MODELS
    assert "current.modelId !== defaultModelId" not in USE_AGENT_MODELS


def test_chat_interface_does_not_mount_second_use_agent_models_hook():
    assert "useAgentModels" not in CHAT_INTERFACE

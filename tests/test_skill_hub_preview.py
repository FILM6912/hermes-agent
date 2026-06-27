from unittest.mock import MagicMock, patch

from app.domain.skill_hub_preview import _bundle_skill_markdown, fetch_hub_skill_preview


class _FakeBundle:
    def __init__(self, files):
        self.files = files


def test_bundle_skill_markdown_prefers_skill_md():
    bundle = _FakeBundle({"SKILL.md": "---\nname: x\n---\n\n# Hello\n"})
    assert "# Hello" in _bundle_skill_markdown(bundle)


def test_bundle_skill_markdown_decodes_bytes():
    bundle = _FakeBundle({"SKILL.md": b"# Bytes\n"})
    assert _bundle_skill_markdown(bundle) == "# Bytes\n"


def test_fetch_hub_skill_preview_requires_identifier():
    data = fetch_hub_skill_preview("")
    assert data["success"] is False
    assert data["error"] == "identifier required"


def test_fetch_hub_skill_preview_prefers_raw_github(allow_outbound_network):
    data = fetch_hub_skill_preview("skills-sh/anthropics/skills/xlsx")
    assert data["success"] is True
    assert data.get("content")
    assert data.get("fallback") == "raw-github"


@patch("app.domain.skill_hub_preview._raw_github_preview", return_value=None)
@patch("hermes_cli.skills_hub._resolve_source_meta_and_bundle")
@patch("tools.skills_hub.create_source_router")
@patch("tools.skills_hub.GitHubAuth")
def test_fetch_hub_skill_preview_falls_back_when_bundle_empty(
    _auth,
    _router,
    resolve_bundle,
    _raw,
):
    meta = MagicMock()
    meta.name = "xlsx"
    meta.description = "Spreadsheets"
    meta.identifier = "skills-sh/anthropics/skills/xlsx"
    meta.source = "skills.sh"
    meta.trust_level = "trusted"
    resolve_bundle.return_value = (meta, None, "skills-sh")

    with patch(
        "app.domain.skill_hub_preview._raw_github_preview",
        return_value={
            "success": True,
            "name": "xlsx",
            "content": "# Preview\n",
            "fallback": "raw-github",
        },
    ) as raw_mock:
        data = fetch_hub_skill_preview("skills-sh/anthropics/skills/xlsx")

    assert data["success"] is True
    assert data["content"] == "# Preview\n"
    raw_mock.assert_called()

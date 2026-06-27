from app.domain.skill_hub_search import (
    group_hub_search_results,
    hub_search_limit,
    is_repo_hub_query,
    repo_slug_from_identifier,
    serialize_hub_search_meta,
)


class _FakeMeta:
    def __init__(self):
        self.identifier = "skills-sh/anthropics/skills/xlsx"
        self.name = "xlsx"
        self.description = "Spreadsheets"
        self.source = "skills.sh"
        self.trust_level = "trusted"
        self.repo = "anthropics/skills"
        self.extra = {
            "installs": 103935,
            "detail_url": "https://skills.sh/anthropics/skills/xlsx",
            "repo_url": "https://github.com/anthropics/skills",
        }


def test_is_repo_hub_query():
    assert is_repo_hub_query("anthropics/skills") is True
    assert is_repo_hub_query("anthropics/skills/xlsx") is False
    assert is_repo_hub_query("xlsx") is False


def test_hub_search_limit_raises_for_repo_query():
    assert hub_search_limit("anthropics/skills", 12) == 50
    assert hub_search_limit("xlsx", 12) == 12


def test_repo_slug_from_identifier():
    assert repo_slug_from_identifier("skills-sh/anthropics/skills/xlsx") == (
        "anthropics/skills"
    )


def test_serialize_hub_search_meta_includes_repo_and_installs():
    row = serialize_hub_search_meta(_FakeMeta())
    assert row["repo"] == "anthropics/skills"
    assert row["installs"] == 103935


def test_group_hub_search_results():
    rows = [
        {"repo": "anthropics/skills", "name": "xlsx", "installs": 100},
        {"repo": "anthropics/skills", "name": "pptx", "installs": 200},
        {"repo": "openai/skills", "name": "pdf", "installs": 50},
    ]
    groups = group_hub_search_results(rows)
    assert len(groups) == 2
    assert groups[0]["repo"] == "anthropics/skills"
    assert groups[0]["skill_count"] == 2
    assert groups[0]["total_installs"] == 300

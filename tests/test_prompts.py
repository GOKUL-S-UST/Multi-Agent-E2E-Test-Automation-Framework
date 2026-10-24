import pytest

from prompts import load_prompt


@pytest.mark.parametrize(
    "name", ["interpreter", "scenario_generator", "test_case_generator", "code_generator", "healer"]
)
def test_prompts_load_and_render(name):
    prompt = load_prompt(name)
    assert prompt.system and prompt.user_template
    _, user = prompt.render(target_url="https://example.com")
    assert "https://example.com" in user

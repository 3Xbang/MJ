from ai_film_editor_nodes.nodes.video.cast_ref_generator_node import (
    apply_gender_choice, build_cast_edit_prompt, build_cast_prompt, parse_gender_choices,
)
from ai_film_editor_nodes.webui.graphs import build_prompt


def test_character_card_gender_overrides_the_analysis():
    choices = parse_gender_choices("小舟:female, 小宇:男")
    woman = apply_gender_choice(
        {"name": "小舟", "gender": "male", "age_range": "25",
         "appearance_en": "long black hair", "default_costume_en": "beige cardigan and pleated skirt"},
        choices,
    )
    prompt = build_cast_prompt(woman, "3D cartoon")
    assert "adult woman, female" in prompt
    assert "adult man" not in prompt
    edit = build_cast_edit_prompt(woman, "3D cartoon")
    assert "[Image_1]" in edit
    assert "adult woman, female" in edit
    assert "Do not draw: man, male, boy, masculine." in edit

    man = apply_gender_choice(
        {"name": "小宇", "gender": "female", "appearance_en": "short curly hair"},
        choices,
    )
    assert "adult man, male" in build_cast_prompt(man, "style")
    assert "Do not draw: woman, female, girl." in build_cast_edit_prompt(man, "style")


def test_asset_step_sends_the_chosen_genders():
    prompt, _ = build_prompt(2, "afe_project", {"cast_genders": "小舟:female"}, "out")
    assert prompt["6"]["inputs"]["genders"] == "小舟:female"

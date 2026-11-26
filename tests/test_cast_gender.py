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


def test_revision_note_replaces_the_wrong_analyzed_look():
    from ai_film_editor_nodes.nodes.video.cast_ref_generator_node import (
        apply_revision_note, parse_cast_notes,
    )
    notes = parse_cast_notes("小舟: 成年女人，黑发扎在脑后，浅米色开衫，卡其百褶裙")
    member = apply_revision_note(apply_gender_choice(
        {"name": "小舟", "gender": "male", "age_range": "25",
         "appearance_en": "Chinese male in his early twenties, wearing a casual shirt and jeans",
         "default_costume_en": "casual shirt and jeans"},
        {"小舟": "female"},
    ), notes)
    prompt = build_cast_prompt(member, "3D cartoon")
    edit = build_cast_edit_prompt(member, "3D cartoon")
    assert "成年女人，黑发扎在脑后，浅米色开衫，卡其百褶裙" in prompt
    assert "Chinese male" not in prompt
    assert "casual shirt and jeans" not in prompt
    assert "adult woman, female" in prompt
    assert "Chinese male" not in edit
    assert "成年女人，黑发扎在脑后" in edit
    assert "Do not draw: man, male, boy, masculine." in edit

    untouched = build_cast_prompt(
        {"name": "胖叔", "appearance_en": "silver curls", "default_costume_en": "white shirt"},
        "style",
    )
    assert "silver curls" in untouched
    assert "wearing white shirt" in untouched


def test_asset_step_sends_the_character_revision():
    prompt, _ = build_prompt(
        2, "afe_project",
        {"cast_notes": "小舟: 成年女人，黑发，米色开衫"},
        "out",
    )
    assert prompt["6"]["inputs"]["revision_notes"] == "小舟: 成年女人，黑发，米色开衫"

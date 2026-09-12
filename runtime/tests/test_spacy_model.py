import spacy


def test_english_model_is_installed():
    assert spacy.load("en_core_web_sm") is not None

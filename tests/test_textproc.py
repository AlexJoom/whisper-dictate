from whisper_dictate.textproc import TextOptions, clean_transcript, is_hallucination

NO_SPACE = TextOptions(trailing_space=False)


def test_english_fillers_and_capitalization():
    assert clean_transcript("um, hello there, uh, how are you?", "en", NO_SPACE) == "Hello there, how are you?"


def test_greek_fillers():
    assert clean_transcript("εε, καλημέρα σας, εμ, τι κάνετε;", "el", NO_SPACE) == "Καλημέρα σας, τι κάνετε;"


def test_greek_short_words_are_kept():
    # "με" and "εμείς" must not be treated as fillers
    assert clean_transcript("έλα με εμένα, εμείς φεύγουμε.", "el", NO_SPACE) == "Έλα με εμένα, εμείς φεύγουμε."


def test_new_line_commands_english():
    out = clean_transcript("first point new line second point new paragraph third", "en", NO_SPACE)
    assert out == "First point\nSecond point\n\nThird"


def test_new_line_commands_greek():
    out = clean_transcript("πρώτο σημείο, νέα γραμμή, δεύτερο σημείο", "el", NO_SPACE)
    assert out == "Πρώτο σημείο\nΔεύτερο σημείο"


def test_trailing_space_added_by_default():
    assert clean_transcript("Hello.", "en") == "Hello. "


def test_hallucinations_are_dropped():
    assert clean_transcript("Υπότιτλοι AUTHORWAVE", "el") == ""
    assert clean_transcript("Thank you.", "en") == ""
    assert is_hallucination("  thanks for watching!  ")


def test_empty_and_whitespace():
    assert clean_transcript("   ", "en") == ""


def test_commands_can_be_disabled():
    opts = TextOptions(voice_commands=False, trailing_space=False)
    assert clean_transcript("say new line please", "en", opts) == "Say new line please"

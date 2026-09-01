"""Post-processing of the raw Whisper transcript ("auto-edits").

Pure functions, no GUI or model dependencies, so they are easy to unit test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Phrases Whisper is known to hallucinate on silence / noise, lowercase, no punctuation.
HALLUCINATIONS = {
    "υπότιτλοι authorwave",
    "υποτιτλοι authorwave",
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "subtitles by the amara org community",
    "you",
    "bye",
    "ευχαριστώ",
    "ευχαριστώ πολύ",
    "σας ευχαριστώ",
    "www.mooji.org",
}

FILLERS = {
    "en": r"\b(?:u+m+|u+h+|uhm+|erm*|hmm+|mm+|ah+|er)\b",
    "el": r"(?<![\wͰ-Ͽ])(?:ε{2,}|εμ+|μμ+|χμ+|αα+)(?![\wͰ-Ͽ])",
}

# Voice commands -> replacement. Matched case-insensitively with optional
# surrounding punctuation.
COMMANDS = [
    (r"new\s+paragraph", "\n\n"),
    (r"new\s+line", "\n"),
    (r"νέα\s+παράγραφος", "\n\n"),
    (r"νέα\s+γραμμή", "\n"),
    (r"αλλαγή\s+γραμμής", "\n"),
    (r"αλλαγή\s+παραγράφου", "\n\n"),
]

_SENTENCE_END = ".!?;…"


@dataclass
class TextOptions:
    remove_fillers: bool = True
    voice_commands: bool = True
    capitalize: bool = True
    trailing_space: bool = True


def _strip_punct(s: str) -> str:
    return re.sub(r"[^\w\s.]", "", s, flags=re.UNICODE).strip().lower()


def is_hallucination(text: str) -> bool:
    key = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE).strip().lower()
    key = re.sub(r"\s+", " ", key)
    return key in HALLUCINATIONS or key == ""


def remove_fillers(text: str, lang: str) -> str:
    pattern = FILLERS.get(lang)
    if not pattern:
        return text
    # filler + optional following punctuation/space
    text = re.sub(pattern + r"[,.]?\s*", "", text, flags=re.IGNORECASE)
    return _tidy_punctuation(text)


def apply_commands(text: str) -> str:
    for pat, repl in COMMANDS:
        text = re.sub(r"[,.;:]?\s*\b" + pat + r"\b[,.;:]?\s*", repl, text, flags=re.IGNORECASE)
    # strip spaces around newlines
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text


def _tidy_punctuation(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # "word ," -> "word,"
    text = re.sub(r"([,.;:!?])\1+", r"\1", text)  # ",," -> ","
    text = re.sub(r"^[,.;:]\s*", "", text)  # leading punctuation left behind
    text = re.sub(r"\n[,.;:]\s*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def capitalize_lines(text: str) -> str:
    def cap(line: str) -> str:
        for i, ch in enumerate(line):
            if ch.isalpha():
                return line[:i] + ch.upper() + line[i + 1 :]
            if not ch.isspace() and ch not in "\"'«(“‘":
                return line
        return line

    return "\n".join(cap(line) for line in text.split("\n"))


def clean_transcript(text: str, lang: str, opts: TextOptions | None = None) -> str:
    """Turn raw Whisper output into text ready to be inserted."""
    opts = opts or TextOptions()
    text = re.sub(r"\s+", " ", text).strip()
    if not text or is_hallucination(text):
        return ""
    if opts.voice_commands:
        text = apply_commands(text)
    if opts.remove_fillers:
        text = "\n".join(remove_fillers(line, lang) for line in text.split("\n"))
    text = _tidy_punctuation(text)
    if not text or is_hallucination(text):
        return ""
    if opts.capitalize:
        text = capitalize_lines(text)
    if opts.trailing_space and not text.endswith("\n"):
        text += " "
    return text

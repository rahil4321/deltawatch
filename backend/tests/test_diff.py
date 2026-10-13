from app.check_engine import build_text_diff, content_hash, normalize_text


def test_normalize_text_collapses_whitespace_and_ignored_phrases() -> None:
    actual = normalize_text("  Price:   999\r\n\r\n Updated just now \n", ["Updated just now"])
    assert actual == "Price: 999"


def test_content_hash_is_deterministic() -> None:
    assert content_hash("deadline: friday") == content_hash("deadline: friday")
    assert content_hash("deadline: friday") != content_hash("deadline: monday")


def test_diff_reports_additions_and_removals() -> None:
    result = build_text_diff("Price: ₹999\nDeadline: 20 October", "Price: ₹1299\nDeadline: 25 October")
    assert "1299" in result["added_text"]
    assert "999" in result["removed_text"]
    assert result["change_percent"] > 0
    assert result["changed_chars"] > 0
    assert "characters" in result["summary"]


def test_identical_text_has_zero_difference() -> None:
    result = build_text_diff("stable content", "stable content")
    assert result["change_percent"] == 0
    assert result["added_text"] == ""
    assert result["removed_text"] == ""

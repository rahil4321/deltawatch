import pytest

from app.check_engine import PageBlockedError, PageCaptureError, classify_http_status, is_access_challenge


@pytest.mark.parametrize("status", [401, 403, 407, 408, 418, 429, 451, 404, 410])
def test_access_or_missing_page_is_not_treated_as_content_change(status):
    with pytest.raises(PageBlockedError):
        classify_http_status(status)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_outage_is_a_check_error(status):
    with pytest.raises(PageCaptureError, match="server error"):
        classify_http_status(status)


def test_normal_status_does_not_raise():
    for status in (200, 201, 301, 302):
        classify_http_status(status)


def test_common_captcha_and_challenge_pages_are_detected():
    assert is_access_challenge("https://example.com/", "Just a moment...", "Checking your browser before accessing the site.")
    assert is_access_challenge("https://example.com/captcha", "", "Please wait")
    assert is_access_challenge("https://example.com/", "Security", "Please verify you are human")


def test_normal_content_is_not_misclassified_as_challenge():
    assert not is_access_challenge("https://example.com/scholarships", "Scholarships", "Applications close on 25 October. Complete the form to apply.")

import pytest
from messages import invalid_youtube_cookies
from engine import DownloadLogger

@pytest.mark.parametrize('message', [
 'The provided YouTube account cookies are no longer valid. They have likely been rotated in the browser.',
 'Your cookies have expired.', 'Your account cookies have been rotated.', 'Your cookies are invalid.'])
def test_explicit_invalid_cookie_warning_is_detected(message):
 events=[]
 DownloadLogger(lambda *event: events.append(event)).warning(message)
 assert invalid_youtube_cookies(message) and ('cookie_warning',message) in events

@pytest.mark.parametrize('message', ['HTTP Error 403: Forbidden','Please sign in to confirm you are not a bot',
 'Cookies have not expired','No cookies provided','Cookie expiration date: 2027-01-01'])
def test_general_errors_do_not_claim_cookies_are_expired(message):
 assert not invalid_youtube_cookies(message)

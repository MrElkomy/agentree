"""Branded email layout: escaping, URL safety, text/HTML parts, and the real email flows."""

import re
from html.parser import HTMLParser

import pytest

from agentree.core.email import OutgoingEmail, branded_email
from agentree.core.email_layout import (
    LOGO_CID,
    EmailAction,
    EmailContent,
    clean_text,
    logo_png,
    render_email,
)
from tests.conftest import WEB_ORIGIN, AppHarness
from tests.helpers import PASSWORD, create_business, signup, unique_email

URL = "https://app.agentree.test/invitations/accept?token=abc_DEF-123"
EVIL = "Acme <script>alert(\"x\")</script> & 'Co'"


def _content(**overrides: object) -> EmailContent:
    values: dict[str, object] = {
        "subject": "You're invited",
        "preheader": "Join the team",
        "heading": f"You're invited to join {EVIL}",
        "paragraphs": [f"Join {EVIL} on Agentree as a member."],
        "action": EmailAction("Accept invitation", URL),
        "footnote": "This invitation expires in 7 days.",
        "reason": "You're receiving this because someone invited you.",
    } | overrides
    return EmailContent(**values)  # type: ignore[arg-type]


def test_dynamic_values_are_escaped_in_html() -> None:
    text, html = render_email(_content())
    assert "<script>" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &#x27;Co&#x27;" in html
    # Plain text carries the raw value (not interpreted by any client).
    assert EVIL in text


def test_action_url_alone_on_its_own_line_in_text() -> None:
    text, _ = render_email(_content())
    assert URL in text.splitlines()
    # Same extraction the test mailer and the E2E Mailpit helper use.
    assert text.split("token=", 1)[1].split()[0] == "abc_DEF-123"


def test_action_url_is_attribute_escaped_in_html() -> None:
    url = 'https://app.agentree.test/x?a=1&token=t"><img/src=x>'
    _, html = render_email(_content(action=EmailAction("Go", url)))
    assert 'href="https://app.agentree.test/x?a=1&amp;token=t&quot;&gt;&lt;img/src=x&gt;"' in html
    assert '"><img' not in html


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<b>x</b>",
        "//evil.example/path",
        "/relative/path",
        "https://ok.example/\nInjected: line",
    ],
)
def test_non_http_or_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        render_email(_content(action=EmailAction("Go", url)))


def test_html_uses_inline_logo_and_no_external_resources() -> None:
    _, html = render_email(_content())
    assert f'src="cid:{LOGO_CID}"' in html
    assert 'alt="Agentree"' in html
    srcs = re.findall(r'src="([^"]*)"', html)
    assert srcs == [f"cid:{LOGO_CID}"]
    assert "<link" not in html and "@import" not in html and "url(" not in html
    assert "Your AI Team. Always On." in html


class _Attrs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.styles: list[str] = []
        self.unknown_attrs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        known = {"style", "role", "width", "height", "cellspacing", "cellpadding", "border",
                 "bgcolor", "align", "class", "href", "target", "src", "alt", "lang", "xmlns",
                 "charset", "name", "content"}  # fmt: skip
        for key, value in attrs:
            if key == "style" and value:
                self.styles.append(value)
            if key not in known:
                self.unknown_attrs.add(key)


def test_html_attributes_are_well_formed() -> None:
    _, html = render_email(_content())
    parser = _Attrs()
    parser.feed(html)
    # A stray double quote inside a style value would split it into bogus attributes.
    assert parser.unknown_attrs == set()
    button = next(s for s in parser.styles if "display:inline-block" in s)
    assert "color:#FFFFFF" in button and "font-weight:700" in button
    visible_text = [s for s in parser.styles if "font-size" in s and "display:none" not in s]
    assert visible_text and all("font-family:Inter, " in s for s in visible_text)


def test_text_part_has_footer_and_no_html() -> None:
    text, _ = render_email(_content(action=None, footnote=None))
    assert "<" not in text.replace(EVIL, "")
    assert text.rstrip().endswith("Agentree - Your AI Team. Always On.")
    assert "You're receiving this because someone invited you." in text


def test_control_characters_are_stripped_from_subject_and_text() -> None:
    assert clean_text("Acme\r\nBcc: victim@example.com") == "Acme Bcc: victim@example.com"
    message = branded_email(
        "a@example.com",
        _content(subject="Invite to Acme\r\nBcc: x@example.com", heading="Hi\nthere\u2028you"),
    )
    assert "\r" not in message.subject and "\n" not in message.subject
    assert message.body.splitlines()[0] == "Hi there you"


def test_branded_email_carries_text_and_html() -> None:
    message = branded_email("a@example.com", _content())
    assert isinstance(message, OutgoingEmail)
    assert message.html is not None and "cid:agentree-logo" in message.html
    assert URL in message.body.splitlines()


def test_logo_is_packaged_png() -> None:
    data = logo_png()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) < 15_000


# --- real flows ----------------------------------------------------------------------------


def _assert_branded(message: OutgoingEmail, link_prefix: str) -> None:
    assert message.html is not None
    assert "cid:agentree-logo" in message.html
    links = [line for line in message.body.splitlines() if line.startswith(link_prefix)]
    assert len(links) == 1
    assert links[0] in message.html  # same link behind the button / raw link


async def test_verification_and_resend_emails_are_branded(harness: AppHarness) -> None:
    email = unique_email()
    c = harness.new_client()
    r = await c.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 202
    first = harness.mailer.last_to(email)
    assert first.subject == "Verify your Agentree email"
    _assert_branded(first, f"{WEB_ORIGIN}/verify-email?token=")
    assert "This link expires in 24 hours." in first.body

    r = await c.post("/api/auth/resend-verification", json={"email": email})
    assert r.status_code == 202
    second = harness.mailer.last_to(email)
    assert second is not first
    _assert_branded(second, f"{WEB_ORIGIN}/verify-email?token=")
    r = await c.post("/api/auth/verify-email", json={"token": harness.mailer.token_for(email)})
    assert r.status_code == 200


async def test_signup_attempt_and_reset_emails_are_branded(harness: AppHarness) -> None:
    acc = await signup(harness, login=False)
    c = harness.new_client()
    await c.post("/api/auth/register", json={"email": acc.email, "password": PASSWORD + "x"})
    notice = harness.mailer.last_to(acc.email)
    assert notice.subject == "Agentree sign-up attempt"
    _assert_branded(notice, f"{WEB_ORIGIN}/login")
    assert "token=" not in notice.body and "token=" not in (notice.html or "")

    r = await c.post("/api/auth/password-reset/request", json={"email": acc.email})
    assert r.status_code == 202
    reset = harness.mailer.last_to(acc.email)
    assert reset.subject == "Reset your Agentree password"
    _assert_branded(reset, f"{WEB_ORIGIN}/reset-password?token=")
    assert "This link expires in 1 hour." in reset.body
    assert "If you didn't ask for this, you can ignore this email." in reset.body


async def test_invitation_email_is_branded_and_escapes_business_name(
    harness: AppHarness,
) -> None:
    owner = await signup(harness)
    business = await create_business(owner, name='Acme <b>"Bold"</b>')
    invitee = unique_email()
    r = await owner.client.post(
        f"/api/businesses/{business['id']}/invitations", json={"email": invitee, "role": "admin"}
    )
    assert r.status_code == 201, r.text
    message = harness.mailer.last_to(invitee)
    assert message.subject == 'You\'re invited to Acme <b>"Bold"</b> on Agentree'
    _assert_branded(message, f"{WEB_ORIGIN}/invitations/accept?token=")
    assert message.html is not None
    assert "<b>" not in message.html
    assert "Acme &lt;b&gt;&quot;Bold&quot;&lt;/b&gt;" in message.html
    assert "as an admin" in message.body
    assert "This invitation expires in 7 days." in message.body
    assert harness.mailer.token_for(invitee)

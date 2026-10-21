"""Branded transactional email layout: one responsive HTML template plus a plain-text part.

Feature modules describe an email as data (`EmailContent`) and call `render_email`; they never
write HTML. Every dynamic value is escaped here, so user-controlled text (a business name, an
inviter's name) can be passed as-is.

Compatibility rules for the HTML: table layout, inline styles, no external resources (no web
fonts, no hosted images, no tracking pixels). The logo is a small PNG attached inline and
referenced as `cid:agentree-logo` (see `SmtpEmailSender`); email clients do not render SVG.

The plain-text part is the canonical body: the action URL sits alone on its own line so it stays
clickable and machine-extractable.
"""

import html
import importlib.resources
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from urllib.parse import urlsplit

LOGO_CID = "agentree-logo"
SLOGAN = "Your AI Team. Always On."

# Brand tokens (docs/brand/BRAND_IDENTITY.md). Mirrored here because email cannot use CSS vars.
_BRAND = "#0052FC"
_INK = "#101B2B"
_PAPER = "#F7F9FC"
_SURFACE = "#FFFFFF"
_MUTED = "#59697B"
_LINE = "#E3EAF2"
# Single quotes only: these values are embedded in double-quoted style="" attributes.
_FONT = "Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

_ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class EmailAction:
    label: str
    url: str


@dataclass(frozen=True)
class EmailContent:
    subject: str
    preheader: str
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    action: EmailAction | None = None
    footnote: str | None = None
    # Footer line explaining why the recipient got this email ("You're receiving this because...").
    reason: str | None = None


@cache
def logo_png() -> bytes:
    """The inline logo (160 px display width, rendered at 2x from agentree-wordmark.svg)."""
    return importlib.resources.files("agentree.core").joinpath("assets/email-logo.png").read_bytes()


def clean_text(value: str) -> str:
    """Single-line text: control characters and line/paragraph separators become spaces.

    Used for subjects (prevents header injection) and every inline text value, so user-controlled
    input cannot fake extra lines or links in the plain-text part.
    """
    cleaned = "".join(" " if unicodedata.category(ch) in {"Cc", "Zl", "Zp"} else ch for ch in value)
    return " ".join(cleaned.split())


def plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


def _checked_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES or not parts.netloc:
        raise ValueError("email action URL must be an absolute http(s) URL")
    if any(ch.isspace() or unicodedata.category(ch) == "Cc" for ch in url):
        raise ValueError("email action URL must not contain whitespace or control characters")
    return url


def _e(value: str) -> str:
    return html.escape(clean_text(value), quote=True)


def render_text(content: EmailContent) -> str:
    lines = [clean_text(content.heading), ""]
    for paragraph in content.paragraphs:
        lines += [clean_text(paragraph), ""]
    if content.action is not None:
        url = _checked_url(content.action.url)
        lines += [f"{clean_text(content.action.label)}:", url, ""]
    if content.footnote:
        lines += [clean_text(content.footnote), ""]
    lines.append("--")
    if content.reason:
        lines.append(clean_text(content.reason))
    lines.append(f"Agentree - {SLOGAN}")
    return "\n".join(lines) + "\n"


# Inline styles (email clients drop most <style> rules, so everything that matters is inline).
_TABLE = 'role="presentation" cellspacing="0" cellpadding="0" border="0"'
_TEXT = f"font-family:{_FONT};"
_S_HEADING = (
    f"padding:0 0 16px 0;{_TEXT}font-size:24px;line-height:32px;font-weight:700;color:{_INK};"
)
_S_PARAGRAPH = f"padding:0 0 16px 0;{_TEXT}font-size:16px;line-height:24px;color:{_INK};"
_S_SMALL = f"{_TEXT}font-size:13px;line-height:20px;color:{_MUTED};"
_S_BUTTON_CELL = f"border-radius:8px;background-color:{_BRAND};"
_S_BUTTON = (
    f"display:inline-block;padding:13px 28px;{_TEXT}font-size:16px;line-height:20px;"
    "font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:8px;"
)
_S_RAW_LINK = f"color:{_BRAND};text-decoration:underline;word-break:break-all;"
_S_PREHEADER = (
    "display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;mso-hide:all;"
    f"font-size:1px;line-height:1px;color:{_PAPER};"
)
_S_LOGO = (
    "display:block;border:0;outline:none;text-decoration:none;width:160px;height:39px;"
    f"{_TEXT}font-size:22px;font-weight:700;color:{_INK};"
)
_S_CARD = (
    f"background-color:{_SURFACE};border:1px solid {_LINE};border-radius:12px;padding:36px 40px;"
)
_S_FOOTER = f"padding:24px 4px 0 4px;{_TEXT}font-size:12px;line-height:18px;color:{_MUTED};"
_HEAD_STYLE = f"""
  body {{ margin:0; padding:0; width:100% !important; -webkit-text-size-adjust:100%; }}
  a {{ color:{_BRAND}; }}
  @media only screen and (max-width:600px) {{
    .ag-outer {{ padding:16px 8px !important; }}
    .ag-card {{ padding:28px 20px !important; }}
    .ag-heading {{ font-size:22px !important; line-height:30px !important; }}
  }}
"""
# Filler keeps clients from appending body text to the preheader in the inbox preview.
_PREHEADER_FILLER = "&#847;&zwnj;&nbsp;" * 40


def _button(action: EmailAction) -> str:
    url = html.escape(_checked_url(action.url), quote=True)
    return f"""
<tr><td style="padding:8px 0 24px 0;">
  <table {_TABLE}>
    <tr><td align="center" bgcolor="{_BRAND}" style="{_S_BUTTON_CELL}">
      <a href="{url}" target="_blank" style="{_S_BUTTON}">{_e(action.label)}</a>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:0 0 24px 0;{_S_SMALL}">
  If the button doesn't work, copy and paste this link into your browser:<br>
  <a href="{url}" target="_blank" style="{_S_RAW_LINK}">{url}</a>
</td></tr>"""


def render_html(content: EmailContent) -> str:
    paragraphs = "".join(
        f'<tr><td style="{_S_PARAGRAPH}">{_e(p)}</td></tr>' for p in content.paragraphs
    )
    action = _button(content.action) if content.action is not None else ""
    footnote = (
        f'<tr><td style="padding:0;{_S_SMALL}">{_e(content.footnote)}</td></tr>'
        if content.footnote
        else ""
    )
    reason = f'<p style="margin:0 0 8px 0;">{_e(content.reason)}</p>' if content.reason else ""
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{_e(content.subject)}</title>
<style>{_HEAD_STYLE}</style>
</head>
<body style="margin:0;padding:0;background-color:{_PAPER};">
<div style="{_S_PREHEADER}">{_e(content.preheader)}{_PREHEADER_FILLER}</div>
<table width="100%" {_TABLE} bgcolor="{_PAPER}" style="background-color:{_PAPER};">
<tr><td class="ag-outer" align="center" style="padding:32px 16px;">
<!--[if mso]><table width="560" {_TABLE}><tr><td><![endif]-->
<table width="100%" {_TABLE} style="max-width:560px;width:100%;">
  <tr><td style="padding:0 0 20px 4px;">
    <img src="cid:{LOGO_CID}" width="160" height="39" alt="Agentree" style="{_S_LOGO}">
  </td></tr>
  <tr><td class="ag-card" bgcolor="{_SURFACE}" style="{_S_CARD}">
    <table width="100%" {_TABLE}>
      <tr><td class="ag-heading" style="{_S_HEADING}">{_e(content.heading)}</td></tr>
      {paragraphs}{action}{footnote}
    </table>
  </td></tr>
  <tr><td style="{_S_FOOTER}">
    {reason}<p style="margin:0;"><strong style="color:{_INK};">Agentree</strong>
    &middot; {SLOGAN}</p>
  </td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>
"""


def render_email(content: EmailContent) -> tuple[str, str]:
    """Return (plain_text, html) for `content`. Raises ValueError for a non-http(s) action URL."""
    return render_text(content), render_html(content)

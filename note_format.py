# coding: utf-8
"""Pure helpers for Evernote note fields. No Sublime or network imports."""

from __future__ import unicode_literals

import re

try:
    _text_type = unicode
    _bytes_type = str
except NameError:  # Python 3
    _text_type = str
    _bytes_type = bytes

TITLE_MAX = 255
TAG_MAX = 100
CONTENT_MAX = 5242880

_IMG = re.compile(r'<img\b([^>]*)>', re.IGNORECASE)
_SRC = re.compile(r'\bsrc\s*=\s*"([^"]*)"', re.IGNORECASE)
_ALT = re.compile(r'\balt\s*=\s*"([^"]*)"', re.IGNORECASE)
_DROP_BLOCKS = re.compile(
    r'<(script|style|iframe|object|embed|form)\b[^>]*>.*?</\1>',
    re.IGNORECASE | re.DOTALL,
)
_DROP_TAGS = re.compile(
    r'</?(?:script|style|iframe|object|embed|form|input|textarea|button'
    r'|meta|link|html|body|head)\b[^>]*>',
    re.IGNORECASE,
)
_CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def as_text(value):
    if value is None:
        return ''
    if isinstance(value, _text_type):
        return value
    if isinstance(value, _bytes_type):
        return value.decode('utf-8')
    return _text_type(value)


def normalize_title(title):
    return as_text(title).strip()


def title_error(title):
    cleaned = normalize_title(title)
    if not cleaned:
        return 'Title is required.'
    if len(cleaned) > TITLE_MAX:
        return 'Title must be at most 255 characters.'
    return None


def normalize_tags(tags):
    """Split a comma-separated tag string and drop blanks and duplicates.

    Evernote rejects tags with leading or trailing whitespace, so "a, b"
    must become ["a", "b"] rather than ["a", " b"].
    """
    if tags is None:
        return []
    if isinstance(tags, (list, tuple)):
        raw = list(tags)
    else:
        raw = as_text(tags).split(',')
    seen = []
    for item in raw:
        name = as_text(item).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def tags_error(tags):
    for name in tags:
        if len(name) > TAG_MAX:
            return 'Tag "%s" is longer than 100 characters.' % name
    return None


def resolve_note_fields(metadata, title, tags, title_provided, tags_provided):
    """Pick the title and tags to send.

    title_provided / tags_provided distinguish "the caller omitted this"
    from "the caller set it to an empty string". An empty tag string is a
    real answer (no tags). An omitted title falls through to metadata, then
    to a prompt.
    """
    meta = metadata or {}
    resolved_title = None
    if title_provided:
        cleaned = normalize_title(title)
        if cleaned:
            resolved_title = cleaned
    if resolved_title is None and meta.get('title'):
        cleaned = normalize_title(meta.get('title'))
        if cleaned:
            resolved_title = cleaned

    if tags_provided:
        resolved_tags = normalize_tags(tags)
        tags_ready = True
    elif 'tags' in meta:
        resolved_tags = normalize_tags(meta.get('tags'))
        tags_ready = True
    else:
        resolved_tags = []
        tags_ready = False
    return resolved_title, resolved_tags, tags_ready


def _img_to_link(match):
    blob = match.group(1)
    src_match = _SRC.search(blob)
    alt_match = _ALT.search(blob)
    src = src_match.group(1) if src_match else ''
    alt = alt_match.group(1) if alt_match else ''
    label = alt or src or 'image'
    if not src:
        return label
    return '<a href="%s">%s</a>' % (src, label)


def markdown_html_to_enml_body(html):
    text = as_text(html)
    text = _DROP_BLOCKS.sub('', text)
    text = _DROP_TAGS.sub('', text)
    text = _IMG.sub(_img_to_link, text)
    text = _CTRL.sub('', text)
    return text


def build_enml(html):
    body = markdown_html_to_enml_body(html)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">'
        '<en-note>' + body + '</en-note>'
    )


def content_error(enml):
    encoded = as_text(enml).encode('utf-8')
    if len(encoded) > CONTENT_MAX:
        return "Note content exceeds Evernote's size limit."
    return None


def require_oauth_fields(status, fields, require_secret=False):
    """Return the OAuth field map, or raise ValueError.

    The message names the OAuth problem or the HTTP status. It does not
    include the response body, which can contain a token.
    """
    try:
        code = int(status or 0)
    except (TypeError, ValueError):
        code = 0
    payload = fields or {}
    token = payload.get('oauth_token')
    secret = payload.get('oauth_token_secret')
    if code != 200:
        problem = payload.get('oauth_problem') or ('HTTP %s' % code)
        raise ValueError('Evernote OAuth failed: %s' % problem)
    if not token or (require_secret and not secret):
        problem = payload.get('oauth_problem') or 'response did not include a token'
        raise ValueError('Evernote OAuth failed: %s' % problem)
    return payload

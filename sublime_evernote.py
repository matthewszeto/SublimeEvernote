#coding:utf-8
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_ROOT, 'lib')
# Sublime loads this file by path and does not put the package directory on
# sys.path. note_format lives next to this file; Evernote and its
# dependencies live in lib/.
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import note_format

import evernote.edam.type.ttypes as Types
import evernote.edam.error.ttypes as Errors
from evernote.api.client import EvernoteClient
import sublime
import sublime_plugin
import markdown2
import webbrowser

callbackUrl = 'http://127.0.0.1/sublimeevernote/callback'
settings = sublime.load_settings('SublimeEvernote.sublime-settings')

_MISSING = object()
_AUTH_ERRORS = (
    Errors.EDAMErrorCode.INVALID_AUTH,
    Errors.EDAMErrorCode.AUTH_EXPIRED,
)
MISSING_CREDENTIALS = (
    'Evernote consumer_key and consumer_secret are not set. '
    'Open Evernote Settings and add the API key for this plugin.'
)


def to_api_str(value):
    """Encode text for this Python 2 Thrift stack, which writes raw bytes."""
    if value is None:
        return ''
    try:
        text_type = unicode
    except NameError:
        text_type = str
    if isinstance(value, text_type):
        if text_type is str:
            return value
        return value.encode('utf-8')
    return value


def configured_host():
    return settings.get('service_host') or 'www.evernote.com'


def configured_sandbox():
    sandbox = settings.get('sandbox')
    if sandbox is None:
        return False
    return bool(sandbox)


def get_evernote_client(token=None):
    host = configured_host()
    sandbox = configured_sandbox()
    if token:
        return EvernoteClient(token=token, service_host=host, sandbox=sandbox)
    key = settings.get('consumer_key') or ''
    secret = settings.get('consumer_secret') or ''
    if not key or not secret:
        return None
    return EvernoteClient(
        consumer_key=key,
        consumer_secret=secret,
        service_host=host,
        sandbox=sandbox,
    )


class SendToEvernoteCommand(sublime_plugin.TextCommand):
    def __init__(self, view):
        sublime_plugin.TextCommand.__init__(self, view)
        self.window = view.window() or sublime.active_window()

    def _require_window(self):
        if self.window is None:
            sublime.error_message('No window is available for Evernote.')
            return False
        return True

    def to_markdown_html(self):
        contents = ''
        for sel in self.view.sel():
            contents += self.view.substr(sel) + '\n\n'

        if not contents.strip():
            region = sublime.Region(0, self.view.size())
            contents = self.view.substr(region)

        return markdown2.markdown(contents, extras=[
            'footnotes',
            'fenced-code-blocks',
            'cuddled-lists',
            'code-friendly',
            'metadata',
        ])

    def connect(self, callback, title=_MISSING, tags=_MISSING):
        if not self._require_window():
            return
        client = get_evernote_client()
        if client is None:
            sublime.error_message(MISSING_CREDENTIALS)
            return

        sublime.status_message('authenticate..., please wait...')
        try:
            request_token = client.get_request_token(callbackUrl)
            authorize_url = client.get_authorize_url(request_token)
        except Exception as e:
            sublime.error_message('Evernote authentication failed: %s' % e)
            return

        def on_verifier(verifier):
            verifier = (verifier or '').strip()
            if not verifier:
                sublime.error_message('The OAuth verifier is required.')
                return
            try:
                access_token = client.get_access_token(
                    request_token['oauth_token'],
                    request_token['oauth_token_secret'],
                    verifier,
                )
            except Exception as e:
                sublime.error_message('Evernote authentication failed: %s' % e)
                return
            settings.set('access_token', access_token)
            sublime.save_settings('SublimeEvernote.sublime-settings')
            sublime.status_message('authenticate ok')
            callback(title=title, tags=tags)

        webbrowser.open(authorize_url)
        self.window.show_input_panel(
            'type Verifier (required):', '', on_verifier, None, None)

    def _clear_access_token(self):
        settings.erase('access_token')
        sublime.save_settings('SublimeEvernote.sublime-settings')

    def send_note(self, title=_MISSING, tags=_MISSING):
        access_token = settings.get('access_token')
        if not access_token:
            return self.connect(self.send_note, title=title, tags=tags)

        client = get_evernote_client(token=access_token)
        if client is None:
            sublime.error_message(MISSING_CREDENTIALS)
            return

        try:
            note_store = client.get_note_store()
        except Exception as e:
            if sublime.ok_cancel_dialog(
                'Could not open the note store (%s). Re-authenticate?' % e
            ):
                self._clear_access_token()
                self.connect(self.send_note, title=title, tags=tags)
            return

        markdown_html = self.to_markdown_html()
        metadata = getattr(markdown_html, 'metadata', None) or {}
        title_provided = title is not _MISSING
        tags_provided = tags is not _MISSING
        resolved_title, resolved_tags, tags_ready = note_format.resolve_note_fields(
            metadata,
            '' if not title_provided else title,
            None if not tags_provided else tags,
            title_provided,
            tags_provided,
        )

        def sendnote(note_title, note_tags):
            err = note_format.title_error(note_title)
            if err:
                sublime.error_message(err)
                return
            note_tags = note_format.normalize_tags(note_tags)
            err = note_format.tags_error(note_tags)
            if err:
                sublime.error_message(err)
                return
            enml = note_format.build_enml(markdown_html)
            err = note_format.content_error(enml)
            if err:
                sublime.error_message(err)
                return

            note = Types.Note()
            note.title = to_api_str(note_format.normalize_title(note_title))
            note.content = to_api_str(enml)
            note.tagNames = [to_api_str(tag) for tag in note_tags]
            try:
                sublime.status_message('please wait...')
                created = note_store.createNote(access_token, note)
                sublime.status_message('send success guid:%s' % created.guid)
                sublime.message_dialog('success')
            except Errors.EDAMUserException as e:
                if e.errorCode in _AUTH_ERRORS:
                    self._clear_access_token()
                    self.connect(
                        self.send_note,
                        title=note_format.normalize_title(note_title),
                        tags=note_tags,
                    )
                    return
                sublime.error_message('Evernote rejected the note (%s).' % e)
            except Exception as e:
                sublime.error_message('error %s' % e)

        def prompt_tags(note_title):
            if not self._require_window():
                return

            def on_tags(raw):
                sendnote(note_title, raw)

            self.window.show_input_panel(
                'Tags (Optional)::', '', on_tags, None, None)

        def prompt_title():
            if not self._require_window():
                return

            def on_title(raw):
                cleaned = note_format.normalize_title(raw)
                err = note_format.title_error(cleaned)
                if err:
                    sublime.error_message(err)
                    prompt_title()
                    return
                if tags_ready:
                    sendnote(cleaned, resolved_tags)
                else:
                    prompt_tags(cleaned)

            self.window.show_input_panel(
                'Title (required)::', '', on_title, None, None)

        if not resolved_title:
            prompt_title()
            return
        err = note_format.title_error(resolved_title)
        if err:
            sublime.error_message(err)
            return
        if not tags_ready:
            prompt_tags(resolved_title)
            return
        sendnote(resolved_title, resolved_tags)

    def run(self, edit):
        if not settings.get('access_token'):
            self.connect(self.send_note)
        else:
            self.send_note()

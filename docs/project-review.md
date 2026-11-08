# SublimeEvernote project review

Reviewed `master` at `62eecca` (8 Nov 2014, 01:25 Asia/Shanghai). This is a project review of the plugin as it stands, not a pull-request diff. The follow-up commit on this branch applies the fixes listed at the end. Vendored Thrift stubs under `lib/evernote/edam/` and `lib/thrift/` were treated as generated code and were not line-audited.

## What the project does

SublimeEvernote is a Sublime Text 2 plugin. `Send to evernote` takes the current selection, or the whole buffer when the selection is empty, renders it with `markdown2` (including a leading `---` metadata block for title and tags), and creates an Evernote note through the EDAM Thrift API. Authentication is OAuth 1.0a: the plugin opens a browser, the user pastes the verifier, and the access token is stored in `SublimeEvernote.sublime-settings`.

The runnable plugin code is `sublime_evernote.py` (129 lines) plus `lib/evernote/api/client.py`. Everything else in `lib/` is vendored (`markdown2`, `oauth2`, `httplib2`, a Linux `httplib`, and generated Evernote/Thrift stubs). There are no tests and no package default settings file.

## Verdict

On Sublime Text 2 the send path can drop a note or submit data Evernote rejects. The OAuth consumer secret is committed in the plugin source. The plugin does not load on Sublime Text 3 or 4. The follow-up fixes the send-path defects and removes the in-source secret. It does not re-platform the vendored Python 2 stack.

## Findings

### 1. A failed note-store connection still tries to send

`send_note` sets `noteStore` to `None`, then on any `get_note_store()` exception shows a dialog and optionally starts OAuth. It does not return. Execution continues, opens the title panel, and calls `noteStore.createNote`. Cancelling the dialog does the same. Confirming it stacks the verifier panel on top of the title panel and then fails the send with `AttributeError`.

`sublime_evernote.py` lines 73-85 and 97.

### 2. Re-authentication loses the title the user just typed

After `createNote` raises `EDAMUserException` with code 9 (`AUTH_EXPIRED`), the plugin calls `send_note(title=..., tags=...)`. The retry branch is:

```python
elif not kwargs.get("tags"):
    on_title(markdown_html.metadata['title'])
```

`tags=""` is falsy, so an optional empty tag field takes this branch. If the title was typed into the panel and is not in the Markdown metadata, `metadata['title']` raises `KeyError` after the user has already completed OAuth. The note is never created. If the metadata title differs from the typed title, the retry silently sends the metadata title instead.

The same branch does not run for `INVALID_AUTH` (code 8). That path shows a generic retry dialog and then falls through into the bug in finding 1.

`sublime_evernote.py` lines 100-123.

### 3. OAuth consumer secret is hardcoded

`consumer_key` and `consumer_secret` are module-level literals in `sublime_evernote.py` lines 13-14. The secret is an application credential, it is in git history, and anyone with the source can impersonate this API key. There is no settings override. The access token stored in the User settings file is the right place for a per-user token; the consumer secret should not live in code.

Removing the literal does not rotate the key. Rotation has to happen in Evernote's developer console. The old value remains reachable from git history.

### 4. Tag strings with spaces are rejected by Evernote

`note.tagNames = tags and tags.split(",") or []` keeps the space after each comma. EDAM's tag rule (`EDAM_TAG_NAME_REGEX` in `lib/evernote/edam/limits/constants.py`) disallows leading and trailing whitespace. The metadata example in the readme is `tags: tag1,tag2`. The snippet and a normal "tag1, tag2" entry produce ` tag2`, and `createNote` fails with `BAD_DATA_FORMAT`.

`sublime_evernote.py` line 94.

### 5. Markdown images are not valid ENML

`markdown2` emits `<img>` (`lib/markdown2.py` around line 1124). Evernote note content must be ENML. `<img>` is not an ENML element; images have to be `en-media` resources. A note that contains a Markdown image fails with `ENML_VALIDATION` (error code 11). The readme presents Markdown as supported, and this path does not upload resources.

Pasted `<script>`, `<style>`, `<iframe>`, and similar tags fail the same validation.

### 6. OAuth HTTP failures become a KeyError

`EvernoteClient.get_request_token` and `get_access_token` (`lib/evernote/api/client.py` lines 32-56) do not check the HTTP status. An error body parses to a dict without `oauth_token`, and the next lookup raises `KeyError`. `connect` does not catch that, so the user gets a traceback in the console instead of a dialog. An empty verifier takes the same path.

### 7. `lib` is imported from the process working directory

`sys.path.insert(0, "lib")` (`sublime_evernote.py` line 3) is a relative path. Sublime's working directory is not the package directory, so `import evernote` depends on wherever the process was started. The package directory is available as `__file__`.

### 8. Linux SSL `httplib` is loaded only if the folder is named `SublimeEvernote`

`lib/httplib2/__init__.py` lines 37-44 load the vendored SSL `httplib` from `packages_path()/SublimeEvernote/lib` and only on Linux. A clone or install under any other directory name skips that override. That override is the fix from commit `4ae23d5` for a Linux build of Python whose stock `httplib` has no SSL. Without it, OAuth to `https://www.evernote.com` fails on those builds.

### 9. Sublime Text 3 and 4 cannot load the plugin

The target in `Readme.md` is Sublime Text 2 (Python 2.6). `sublime.Region(0L, ...)` is a syntax error on Python 3. `lib/evernote/api/client.py`, `lib/oauth2`, `lib/httplib2`, and `lib/httplib.py` use `urllib`, `urlparse`, `StringIO`, and `email.Utils`. Sublime Text 3 and 4 run Python 3. The plugin will not import there. Porting that vendored stack is a separate change and is not part of the follow-up.

### 10. Smaller issues

- Lines 37-41 compute a view encoding and never use it. `view.substr` is already decoded text.
- `SendToEvernoteCommand.__init__` stores `sublime.active_window()` rather than `self.view.window()`, so a command run from a non-active window prompts on the wrong window.
- `TextCommand.__init__` is not called.
- There is no `SublimeEvernote.sublime-settings` default file. The settings command opens the User file, which starts empty, and nothing in the package tells the user which keys exist.
- `sandbox` and the service host are fixed to production (`www.evernote.com`, `sandbox=False`).
- No automated tests cover title, tags, or ENML assembly.

`createNote(access_token, note)` was checked against `Store.__getattr__` and `NoteStore.createNote(authenticationToken, note)`. The wrapper sees a bound method whose arg list is one longer than the call and forwards the token as `authenticationToken`. That call is correct. Title and body `.encode('utf-8')` matches this Thrift stack, which writes strings as raw bytes.

## Applied in the follow-up

The follow-up commit applies the eight fixes below. The rewrite also replaces `0L` with `0` and calls `TextCommand.__init__`. Sublime Text 3 and 4 still cannot import the vendored Python 2 libraries. Uploading images as `en-media`, a local OAuth callback listener, a notebook picker, and rotating the historical consumer secret are unchanged. The secret is no longer read from source. It is still in git history and still needs to be rotated at Evernote.

## Fixes in the follow-up

1. Stop sending when the note store cannot be opened, and preserve the resolved title and tags across re-authentication for both `INVALID_AUTH` and `AUTH_EXPIRED`.
2. Read the consumer key, consumer secret, service host, and sandbox flag from settings. Ship an empty default settings file. Refuse to start OAuth when the key is missing. Do not copy the old secret into the new file.
3. Strip, drop empties, and de-duplicate tags before `createNote`. Reject an empty or over-long title locally.
4. Build ENML in one place: turn `<img>` into links, drop tags ENML will not accept, and strip XML 1.0 control characters.
5. Raise a clear error when an OAuth response has no token, and show that error in a dialog. Ignore a blank verifier.
6. Put the absolute package `lib` directory on `sys.path`.
7. Load the vendored Linux `httplib` from the directory that actually contains `httplib2`.
8. Add unit tests for the pure title, tag, ENML, and OAuth-response helpers.

## Left unchanged

- No Python 3 port of Thrift, `oauth2`, `httplib2`, or `httplib`. Sublime Text 2 remains the runtime.
- Markdown images become links. They are not uploaded as Evernote resources.
- OAuth still asks the user to paste the verifier. There is no local callback listener.
- The consumer secret is still in git history. It needs to be rotated at Evernote.
- Notes still go to the default notebook. There is no notebook picker.

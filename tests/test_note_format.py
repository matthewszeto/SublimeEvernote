import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import note_format


class ResolveFieldsTest(unittest.TestCase):
    def test_typed_title_survives_empty_tags_without_metadata_title(self):
        title, tags, tags_ready = note_format.resolve_note_fields(
            {}, 'My Title', '', True, True)
        self.assertEqual(title, 'My Title')
        self.assertEqual(tags, [])
        self.assertTrue(tags_ready)

    def test_typed_title_wins_over_metadata_title(self):
        metadata = {'title': 'From Markdown', 'tags': 'a, b'}
        title, tags, tags_ready = note_format.resolve_note_fields(
            metadata, 'Typed', '', True, True)
        self.assertEqual(title, 'Typed')
        self.assertEqual(tags, [])
        self.assertTrue(tags_ready)

    def test_metadata_used_when_caller_omits_fields(self):
        metadata = {'title': ' From Markdown ', 'tags': 'a, b, a'}
        title, tags, tags_ready = note_format.resolve_note_fields(
            metadata, '', None, False, False)
        self.assertEqual(title, 'From Markdown')
        self.assertEqual(tags, ['a', 'b'])
        self.assertTrue(tags_ready)

    def test_missing_title_and_tags_ask_for_both(self):
        title, tags, tags_ready = note_format.resolve_note_fields(
            {}, '', None, False, False)
        self.assertIsNone(title)
        self.assertEqual(tags, [])
        self.assertFalse(tags_ready)

    def test_blank_provided_title_falls_through_to_metadata(self):
        title, tags, tags_ready = note_format.resolve_note_fields(
            {'title': 'Kept'}, '   ', None, True, False)
        self.assertEqual(title, 'Kept')
        self.assertFalse(tags_ready)


class TagsAndTitleTest(unittest.TestCase):
    def test_tags_strip_whitespace_and_duplicates(self):
        self.assertEqual(
            note_format.normalize_tags(' tag1, tag2 ,tag1, ,tag3 '),
            ['tag1', 'tag2', 'tag3'])

    def test_tag_list_is_normalized(self):
        self.assertEqual(note_format.normalize_tags([' b ', 'b', '']), ['b'])

    def test_title_rules(self):
        self.assertEqual(note_format.title_error('   '), 'Title is required.')
        self.assertIsNone(note_format.title_error('ok'))
        self.assertIsNotNone(note_format.title_error('x' * 256))

    def test_tag_length(self):
        self.assertIsNone(note_format.tags_error(['ok']))
        self.assertIsNotNone(note_format.tags_error(['t' * 101]))


class EnmlTest(unittest.TestCase):
    def test_wraps_body(self):
        enml = note_format.build_enml('<p>Hello</p>')
        self.assertIn('<en-note><p>Hello</p></en-note>', enml)
        self.assertTrue(enml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))

    def test_image_becomes_a_link(self):
        html = '<p><img src="https://example.com/a.png" alt="diagram" /></p>'
        body = note_format.markdown_html_to_enml_body(html)
        self.assertNotIn('<img', body)
        self.assertIn('<a href="https://example.com/a.png">diagram</a>', body)

    def test_script_block_is_removed(self):
        html = '<p>Hi</p><script>alert(1)</script><p>There</p>'
        body = note_format.markdown_html_to_enml_body(html)
        self.assertNotIn('script', body)
        self.assertNotIn('alert', body)
        self.assertIn('<p>Hi</p>', body)
        self.assertIn('<p>There</p>', body)

    def test_control_characters_are_stripped(self):
        body = note_format.markdown_html_to_enml_body('a\x00b\x07c')
        self.assertEqual(body, 'abc')

    def test_content_over_the_edam_cap(self):
        self.assertIsNone(note_format.content_error('<en-note/>'))
        huge = 'a' * (note_format.CONTENT_MAX + 1)
        self.assertIsNotNone(note_format.content_error(huge))


class OAuthFieldsTest(unittest.TestCase):
    def test_accepts_request_token(self):
        fields = note_format.require_oauth_fields(
            '200',
            {'oauth_token': 't', 'oauth_token_secret': 's'},
            require_secret=True,
        )
        self.assertEqual(fields['oauth_token'], 't')

    def test_http_error_omits_body(self):
        with self.assertRaises(ValueError) as caught:
            note_format.require_oauth_fields(
                401,
                {'oauth_problem': 'consumer_key_rejected', 'oauth_token': 'secret-token'},
            )
        message = str(caught.exception)
        self.assertIn('consumer_key_rejected', message)
        self.assertNotIn('secret-token', message)

    def test_missing_token_on_200(self):
        with self.assertRaises(ValueError) as caught:
            note_format.require_oauth_fields(200, {'oauth_problem': 'verifier_invalid'})
        self.assertIn('verifier_invalid', str(caught.exception))

    def test_request_token_requires_secret(self):
        with self.assertRaises(ValueError):
            note_format.require_oauth_fields(200, {'oauth_token': 't'}, require_secret=True)


if __name__ == '__main__':
    unittest.main()

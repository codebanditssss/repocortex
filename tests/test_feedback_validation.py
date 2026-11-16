from unittest.mock import Mock, patch

import pytest

from repocortex.serve.diff_validation import validate_feedback_diff
from repocortex.serve.feedback import FeedbackJournal
from scripts.verify_persistent_learning import DIFF


@pytest.mark.parametrize('diff', [
    DIFF,
    'diff --git a/fixture.py b/fixture.py\nindex abc..def 100644\n' + DIFF,
    '--- a/q.py\n+++ b/q.py\n@@ -10,0 +11,1 @@\n+inserted\n',
    '--- a/q.py\n+++ b/q.py\n@@ -10,1 +9,0 @@\n-deleted\n',
    '--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+new\n',
    '--- a/old.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-old\n',
    DIFF.replace('-old\n', '-old\n\\ No newline at end of file\n'),
    DIFF.replace('\n', '\r\n'),
    DIFF + '--- a/second.py\n+++ b/second.py\n@@ -3,2 +3,2 @@\n same\n-old\n+new\n',
])
def test_complete_unified_patches_are_accepted(diff):
    validate_feedback_diff(diff)


@pytest.mark.parametrize('diff', [
    '+++ b/q.py\n@@ -10 +10 @@\n-old\n+new\n',
    '--- a/q.py\n+++ b/q.py\n@@ -10,1 +10,0 @@\n+forged\n',
    '--- a/q.py\n+++ b/q.py\n@@ -10,1 +10,1 @@\n+forged\n',
    DIFF + '+extra\n',
    '--- a/q.py\n+++ b/q.py\n@@ -1 +1 @@\n same\n',
    DIFF + 'diff --git a/other.py b/other.py\n@@ -10 +10 @@\n-old\n+new\n',
    DIFF + 'unexpected text\n',
    r'\ No newline at end of file' + '\n' + DIFF,
    DIFF.replace('@@ -10,1 +10,1 @@', '@@ -0,1 +10,1 @@'),
    DIFF.replace('@@ -10,1 +10,1 @@', '@@ -10,0 +10,0 @@'),
    DIFF + '@@ -9 +9 @@\n-old\n+new\n',
    DIFF + '--- a/other.py\n+++ b/other.py\n',
    DIFF + 'GIT binary patch\n',
    '--- /dev/null\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new\n',
])
def test_malformed_patch_never_reads_or_writes_journal(diff):
    client = Mock()
    with pytest.raises(ValueError, match='invalid unified diff'):
        FeedbackJournal(client, 'pilot').append('bug report', diff, ['target'])
    client.query.assert_not_called()


def test_cli_preview_rejects_before_mapping_or_search():
    from scripts import feedback_cli
    with patch.object(feedback_cli, 'functions_from_diff') as mapper:
        with pytest.raises(ValueError, match='invalid unified diff'):
            feedback_cli.review(Mock(), 'pilot', 'bug', DIFF + '+extra\n')
    mapper.assert_not_called()


def test_mcp_rejects_before_loading_or_mutating_graph():
    from scripts import mcp_server
    with patch.object(mcp_server, '_http_mode', False), patch.object(mcp_server, 'get_state') as state:
        with pytest.raises(ValueError, match='invalid unified diff'):
            mcp_server.learn_from_fix('bug', DIFF + '+extra\n')
    state.assert_not_called()

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from repocortex.serve.load import runtime_directory, backend_status
from scripts import feedback_cli


def test_explicit_runtime_precedes_env_and_does_not_change_config():
    with patch.dict('os.environ', {'REPOCORTEX_RUNTIME': '/tmp/from-env'}):
        assert runtime_directory(Path('/app')) == Path('/tmp/from-env')
        assert runtime_directory(Path('/app'), Path('/tmp/explicit')) == Path('/tmp/explicit')


def test_wrong_repository_same_function_count_fails_health():
    ranker = SimpleNamespace(n=10, nodes={'repo:expected': {'label':'Repo'}},
                             client=SimpleNamespace(ping=lambda: {'repo':'repo:wrong','functions':10}))
    assert backend_status(ranker)['mode']=='error'
    ranker.client.ping = lambda: {'repo':'repo:expected','functions':10}
    assert backend_status(ranker)['mode'] == 'live'


def test_receipt_cannot_overwrite_selected_runtime(tmp_path):
    target = tmp_path/'data'/'new.json'
    with patch.object(feedback_cli,'load_ranker') as load, pytest.raises(SystemExit):
        feedback_cli.main(['search','--runtime',str(tmp_path),'--namespace','test','--report','unused',
                           '--output',str(target)])
    load.assert_not_called()
    assert not target.exists()

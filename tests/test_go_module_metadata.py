from pathlib import Path

import pytest

from scripts.index_repository import ValidationError, read_go_modules


def test_ancestor_module_identities_and_nested_boundary(tmp_path):
    (tmp_path / 'go.mod').write_text('module example.com/root\nreplace example.com/external => ../outside\n')
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested/go.mod').write_text('// module fake\nmodule "example.com/nested" // comment\n')
    assert read_go_modules(tmp_path, [('pkg/a.go', ''), ('nested/lib/a.go', '')]) == {'.': 'example.com/root', 'nested': 'example.com/nested'}


def test_module_metadata_is_not_read_for_other_languages(tmp_path):
    (tmp_path / 'go.mod').write_text('invalid')
    assert read_go_modules(tmp_path, [('main.ts', '')]) == {}


@pytest.mark.parametrize('text', ['module ../outside', 'module x\nmodule y', '/* module hidden */', 'module x//y', 'module x\nmodule invalid?'])
def test_invalid_module_is_rejected_rather_than_inheriting(tmp_path, text):
    (tmp_path / 'go.mod').write_text(text)
    with pytest.raises(ValidationError):
        read_go_modules(tmp_path, [('a.go', '')])


def test_module_symlink_is_not_followed(tmp_path):
    other = tmp_path / 'actual'
    other.write_text('module example.com/other')
    (tmp_path / 'go.mod').symlink_to(other)
    with pytest.raises(ValidationError):
        read_go_modules(tmp_path, [('a.go', '')])


def test_index_cli_wires_module_metadata_to_import_call_resolution(tmp_path):
    pytest.importorskip('tree_sitter_go')
    import json
    from scripts.index_repository import build_parser, run
    repo = tmp_path / 'repo'
    (repo / 'cmd').mkdir(parents=True)
    (repo / 'lib').mkdir()
    (repo / 'go.mod').write_text('module example.com/repo\n')
    (repo / 'cmd/main.go').write_text('package main\nimport local "example.com/repo/lib"\nfunc run() { local.Save() }\n')
    (repo / 'lib/store.go').write_text('package storage\nfunc Save() {}\n')
    out = tmp_path / 'index'
    args = build_parser().parse_args(['--repo', str(repo), '--out', str(out), '--scope', 'cmd,lib', '--languages', 'go'])
    result = run(args)
    assert result['go_modules'] == {'.': 'example.com/repo'}
    corpus = json.loads((out / 'data/corpus.json').read_text())
    calls = [edge for edge in corpus['edges'] if edge['rel'] == 'CALLS']
    assert len(calls) == 1
    assert corpus['nodes'][calls[0]['src']]['name'] == 'run'
    assert corpus['nodes'][calls[0]['dst']]['name'] == 'Save'


def test_module_ancestor_symlink_cannot_escape_repository(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'go.mod').write_text('module example.com/outside')
    (repo / 'linked').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        read_go_modules(repo, [('linked/a.go', '')])


@pytest.mark.parametrize('path', ['/outside/a.go', '../outside/a.go'])
def test_module_reader_rejects_nonrelative_sources(tmp_path, path):
    with pytest.raises(ValidationError):
        read_go_modules(tmp_path, [(path, '')])

"""Portable JSON/Parquet/native-model records with atomic lifecycle receipts."""
import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY:' + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(json_bytes(value))
    os.replace(temporary, path)
    if json_bytes(read_json(path)) != path.read_bytes():
        raise ValueError('JSON_ROUNDTRIP_FAILED:' + str(path))


def record_lot4_failure(project, output, error, phase):
    """Revoke any provisional PASS; recording an error never permits another fit."""
    project, output = Path(project), Path(output)
    receipt = {'FINAL_VERDICT': 'FAIL', 'lot': 4, 'utc': utc_now(), 'phase': phase,
               'error_type': type(error).__name__, 'error': str(error), 'stop': True, 'LOT_5_AUTHORIZED': False}
    atomic_json(project / 'LOT_04_FAILURE_RECEIPT.json', receipt)
    report = project / 'LOT_04_LIGHTGBM_REPORT.md'
    report.write_text('# LOT 4 — arrêt fail-closed\n\nVERDICT = FAIL\n\nPhase : ' + phase
                      + '\n\nErreur : ' + str(error) + '\n\nAucun PASS LOT 4 publié ou provisoire ne reste autorisé. '
                      'Les artefacts existants sont conservés pour diagnostic. Les contrôles non terminés restent NOT_TESTED. '
                      'STOP ; LOT 5 non autorisé. Reçu : LOT_04_FAILURE_RECEIPT.json.\n', encoding='utf-8')
    checkpoint = {'project': 'AURUM_QLIB_LAB_V1', 'master_version': 'V2.1', 'lot': 4,
                  'FINAL_VERDICT': 'FAIL', 'failure_receipt_sha256': sha256(project / 'LOT_04_FAILURE_RECEIPT.json'),
                  'previous_checkpoint': 'CHECKPOINT_LOT_03.json', 'previous_checkpoint_sha256': sha256(project / 'CHECKPOINT_LOT_03.json'),
                  'completed_lots': [1, 2, 3], 'LOT_5_AUTHORIZED': False, 'next_authorized_lot': None,
                  'success_checks': 'NOT_CERTIFIED', 'error': str(error)}
    atomic_json(project / 'CHECKPOINT_LOT_04.json', checkpoint)
    master = read_json(project / 'MASTER_STATE.json')
    master.update(current_lot=4, completed_lots=[1, 2, 3], blocked=True, block_reason=str(error),
                  last_checkpoint='CHECKPOINT_LOT_04.json', last_checkpoint_sha256=sha256(project / 'CHECKPOINT_LOT_04.json'),
                  LOT_4_AUTHORIZED=False, LOT_5_AUTHORIZED=False, next_authorized_lot=None,
                  awaiting_operator='Résoudre le FAIL puis instruction opérateur LOT 4')
    master['lot_verdicts']['4'] = 'FAIL'
    atomic_json(project / 'MASTER_STATE.json', master)
    atomic_json(output / 'STOP_RECEIPT.json', receipt)


class ExperimentStore:
    def __init__(self, runs_root):
        self.root = Path(runs_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, experiment_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', experiment_id):
            raise ValueError('INVALID_EXPERIMENT_ID')
        path = self.root / experiment_id
        path.mkdir()  # Never overwrite an existing run, even a partial one.
        (path / 'model').mkdir()
        (path / 'logs').mkdir()
        atomic_json(path / 'status.json', {'run_id': experiment_id, 'status': 'RUNNING', 'start_utc': utc_now(), 'end_utc': None})
        return path

    @staticmethod
    def complete(path):
        files = {p.relative_to(path).as_posix(): {'sha256': sha256(p), 'size': p.stat().st_size}
                 for p in sorted(path.rglob('*')) if p.is_file() and p.name not in {'status.json', 'artifact_manifest.json'}
                 and not p.name.endswith('.tmp')}
        atomic_json(path / 'artifact_manifest.json', {'version': 'AURUM_RUN_ARTIFACT_MANIFEST_V1', 'files': files,
                    'control_exclusions': ['status.json', 'artifact_manifest.json']})
        state = read_json(path / 'status.json')
        state.update(status='COMPLETE', end_utc=utc_now(), artifact_manifest_sha256=sha256(path / 'artifact_manifest.json'))
        atomic_json(path / 'status.json', state)
        ExperimentStore.verify(path)

    @staticmethod
    def verify(path):
        path = Path(path).resolve()
        state = read_json(path / 'status.json')
        if state['status'] != 'COMPLETE' or state['artifact_manifest_sha256'] != sha256(path / 'artifact_manifest.json'):
            raise ValueError('INCOMPLETE_OR_CHANGED_RUN')
        manifest = read_json(path / 'artifact_manifest.json')
        actual = {p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()
                  and p.name not in {'status.json', 'artifact_manifest.json'} and not p.name.endswith('.tmp')}
        if actual != set(manifest['files']):
            raise ValueError('RUN_INVENTORY_DRIFT')
        for name, receipt in manifest['files'].items():
            file = (path / name).resolve()
            if not file.is_relative_to(path) or sha256(file) != receipt['sha256'] or file.stat().st_size != receipt['size']:
                raise ValueError('RUN_ARTIFACT_CHANGED:' + name)
        return manifest

    @staticmethod
    def fail(path, error):
        state = read_json(path / 'status.json')
        state.update(status='FAIL', end_utc=utc_now(), error_type=type(error).__name__, error=str(error))
        atomic_json(path / 'logs/error_receipt.json', state)
        atomic_json(path / 'status.json', state)

"""No real model may run without a current, hash-bound causal certificate."""
import hashlib
import json
import os
from pathlib import Path
from .event_clock import CausalContractError, require

CRITICAL_CONTROLS = (
    'POINT_IN_TIME_FEATURES', 'FEATURE_MAX_TIMESTAMP_CHECK', 'NEXT_BAR_EXECUTION_SEMANTICS',
    'TARGET_FUTURE_ISOLATION', 'FEATURE_TARGET_PHYSICAL_SEPARATION', 'WARMUP_POLICY',
    'TRAIN_VALID_PURGE', 'VALID_TEST_PURGE', 'NO_SPLIT_LABEL_OVERLAP', 'PREPROCESSOR_TRAIN_ONLY',
    'NO_TEMPORAL_SHUFFLE', 'NO_FORWARD_FILL', 'NO_BACKFILL', 'FUTURE_MUTATION_TEST',
    'TRUNCATED_HISTORY_TEST', 'TARGET_MUTATION_ISOLATION_TEST', 'SPLIT_BOUNDARY_ATTACK_TEST',
    'PREPROCESSOR_FUTURE_MUTATION_TEST', 'ROW_APPEND_INVARIANCE_TEST', 'TIMESTAMP_SORT_ATTACK_TEST',
    'FEATURE_PARITY', 'EVENT_ORDER_CONTRACT', 'EQUAL_TIMESTAMP_CAUSAL_ORDER', 'NO_NEXT_BAR_FEATURE_ACCESS')


def file_sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_certificate(certificate, master, *, observed_certificate_sha256, observed_code_hashes):
    require(certificate.get('FINAL_VERDICT') == 'PASS', 'ANTI_LOOKAHEAD_NOT_PASS')
    require(all(certificate.get(name) == 'PASS' for name in CRITICAL_CONTROLS), 'CRITICAL_CAUSAL_CONTROL_NOT_PASS')
    require(master.get('anti_lookahead_certified') is True, 'MASTER_CAUSAL_GATE_NOT_CERTIFIED')
    require(observed_certificate_sha256 == master.get('anti_lookahead_certification_sha256'), 'CERTIFICATION_HASH_INVALID')
    expected = certificate.get('code_hashes')
    require(isinstance(expected, dict) and len(expected) > 0 and expected == observed_code_hashes, 'CAUSAL_CODE_CHANGED_RECERTIFY_LOT_3')
    return certificate


def certificate_path(project_root, kind):
    """Select the current release proof, keeping historical certificate bytes intact."""
    root=Path(project_root).resolve()
    defaults={'anti_lookahead':'ANTI_LOOKAHEAD_CERTIFICATION_V1.json',
              'portfolio':'PORTFOLIO_LOOKAHEAD_TESTS.json'}
    state=json.loads((root/'MASTER_STATE.json').read_text(encoding='utf-8-sig'))
    name=state.get(kind+'_certificate_file',defaults[kind])
    require(isinstance(name,str) and Path(name).name==name,'CERTIFICATE_PATH_INVALID')
    return root/name


def require_certified(project_root, *, invalidate_on_failure=True):
    root = Path(project_root).resolve()
    state_path = root / 'MASTER_STATE.json'
    state = json.loads(state_path.read_text(encoding='utf-8-sig'))
    try:
        path = certificate_path(root,'anti_lookahead')
        certificate = json.loads(path.read_text(encoding='utf-8-sig'))
        actual = {}
        for name in certificate.get('code_hashes', {}):
            component = (root / name).resolve()
            require(component.is_relative_to(root), 'CAUSAL_CODE_PATH_ESCAPE')
            actual[name] = file_sha256(component)
        return validate_certificate(certificate, state, observed_certificate_sha256=file_sha256(path),
                                    observed_code_hashes=actual)
    except (CausalContractError, OSError, ValueError, TypeError) as error:
        if invalidate_on_failure:
            state.update(anti_lookahead_certified=False, anti_lookahead_certification_invalidated=True,
                         anti_lookahead_invalidation_reason=str(error), LOT_4_AUTHORIZED=False)
            temporary = state_path.with_name(state_path.name + '.tmp')
            temporary.write_text(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
            os.replace(temporary, state_path)
        raise CausalContractError('REAL_TRAINING_BLOCKED: ' + str(error)) from error

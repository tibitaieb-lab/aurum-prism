"""Separate, explicit inputs: realized strategy returns and Qlib OOS scores."""
import hashlib
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
from .event_clock import require, event_key
from .experiment_store import ExperimentStore, read_json, sha256

TIME_COLUMNS = ('timestamp_utc', 'interval_start_utc', 'available_at_utc')
PAYLOAD_COLUMNS = (*TIME_COLUMNS, 'available_phase', 'strategy_id', 'asset', 'timeframe', 'return',
                   'source_run_id', 'cost_status', 'reporting_currency', 'provenance')
HASH_KIND = 'SHA256_CANONICAL_RETURN_PAYLOAD_V1'


def payload_hash(frame):
    records = []
    for row in frame[list(PAYLOAD_COLUMNS)].itertuples(index=False, name=None):
        records.append({column: value.isoformat() if column in TIME_COLUMNS else float(value) if column == 'return'
                        else int(value) if column == 'available_phase' else value
                        for column, value in zip(PAYLOAD_COLUMNS, row)})
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def stamp_payload_hashes(frame):
    """For new adapted inputs or COPIES of synthetic fixtures, never AURUM source files."""
    result = frame.copy()
    result['source_hash_kind'] = HASH_KIND
    result['source_hash'] = ''
    for strategy, group in result.groupby('strategy_id', sort=False):
        result.loc[result.strategy_id.eq(strategy), 'source_hash'] = payload_hash(group)
    return result


def validate_return_series(frame, canonical_assets):
    require(set((*PAYLOAD_COLUMNS, 'source_hash', 'source_hash_kind')) <= set(frame.columns), 'RETURN_SERIES_COLUMNS_REQUIRED')
    require(len(frame) > 0, 'EMPTY_RETURN_SERIES')
    for column in TIME_COLUMNS:
        require(isinstance(frame[column].dtype, pd.DatetimeTZDtype) and str(frame[column].dt.tz) == 'UTC'
                and frame[column].notna().all(), 'UTC_AWARE_RETURN_SERIES_REQUIRED:' + column)
    require(frame['return'].dtype == np.dtype('float64') and np.isfinite(frame['return']).all()
            and (frame['return'] > -1).all(), 'FINITE_RETURN_GT_MINUS_ONE_REQUIRED')
    for column in ('strategy_id', 'asset', 'timeframe', 'source_run_id', 'cost_status', 'reporting_currency', 'provenance'):
        require(frame[column].map(lambda x: isinstance(x, str) and len(x) > 0).all(), 'EXPLICIT_METADATA_REQUIRED:' + column)
    require(set(frame.asset) <= set(canonical_assets), 'UNKNOWN_AURUM_CANONICAL_ASSET')
    require(frame.timeframe.nunique() == 1 and frame.reporting_currency.nunique() == 1, 'COMMON_CLOCK_AND_REPORTING_CURRENCY_REQUIRED')
    require(frame.cost_status.nunique() == 1 and set(frame.cost_status) <= {'GROSS_SOURCE_COSTS', 'NET_SOURCE_COSTS'}, 'EXPLICIT_UNIFORM_COST_STATUS_REQUIRED')
    require(frame.available_phase.eq(10).all(), 'REALIZED_RETURN_AVAILABLE_PHASE_MUST_BE_BAR_CLOSE')
    require((frame.interval_start_utc < frame.timestamp_utc).all()
            and (frame.available_at_utc >= frame.timestamp_utc).all(), 'RETURN_INTERVAL_OR_AVAILABILITY_INVALID')
    keys = list(zip(frame.timestamp_utc, frame.strategy_id))
    require(keys == sorted(keys) and len(keys) == len(set(keys)), 'RETURN_SERIES_ORDER_OR_DUPLICATE_INVALID')
    from .portfolio_capacity import validate_capacity
    require(frame.strategy_id.nunique()>=1,'EMPTY_STRATEGY_UNIVERSE')
    validate_capacity(len(frame),int(frame.strategy_id.nunique()),decoded_bytes=int(frame.memory_usage(deep=True).sum()))
    require(frame.source_hash_kind.eq(HASH_KIND).all(), 'EXPLICIT_SUPPORTED_RETURN_HASH_KIND_REQUIRED')
    for strategy, group in frame.groupby('strategy_id', sort=False):
        require(group.asset.nunique() == 1 and group.source_run_id.nunique() == 1, 'STABLE_STRATEGY_IDENTITY_REQUIRED')
        require(group.source_hash.nunique() == 1 and re.fullmatch('[0-9a-f]{64}', group.source_hash.iloc[0]) is not None
                and group.source_hash.iloc[0] == payload_hash(group), 'RETURN_PAYLOAD_HASH_INVALID')
        require(group.interval_start_utc.iloc[1:].reset_index(drop=True).equals(
                group.timestamp_utc.iloc[:-1].reset_index(drop=True)), 'CONTIGUOUS_VALUATION_INTERVALS_REQUIRED_NO_FILL')
    matrix = frame.pivot(index='timestamp_utc', columns='strategy_id', values='return')
    require(not matrix.isna().any().any(), 'MISSING_SERIES_AT_COMMON_CLOCK_FAIL_CLOSED')
    interval = frame.pivot(index='timestamp_utc', columns='strategy_id', values='interval_start_utc')
    require(interval.nunique(axis=1).eq(1).all(), 'COMMON_INTERVAL_START_REQUIRED')
    return matrix


def load_oos_scores(run_folder, canonical_assets):
    """Load TEST scores only. Never expose targets/labels as portfolio scores."""
    run_folder = Path(run_folder)
    ExperimentStore.verify(run_folder)
    spec = read_json(run_folder / 'experiment.json')
    table = pd.read_parquet(run_folder / 'predictions_test.parquet')
    require(table.split.eq('TEST').all() and table.prediction_kind.eq('OOS_STATIC_MODEL').all()
            and table.point_in_time_by_event_contract.eq(True).all(), 'ONLY_CERTIFIED_OOS_SCORES_ALLOWED')
    require(set(table.instrument) <= set(canonical_assets) and np.isfinite(table.prediction).all(), 'INVALID_SCORE_ASSET_OR_VALUE')
    require(table.decision_time.is_unique and table.decision_time.is_monotonic_increasing, 'STRICT_SCORE_CLOCK_REQUIRED')
    for row in table.itertuples():
        require(event_key(row.model_information_end_time, int(row.model_information_end_phase))
                < event_key(row.decision_time, int(row.decision_phase)), 'SCORE_MODEL_FUTURE_INFORMATION')
    return table[['decision_time', 'decision_phase', 'instrument', 'timeframe', 'price_basis', 'prediction']].copy(), {
        'family': 'QLIB_OOS_SCORES', 'source_run_id': spec['experiment_id'],
        'source_predictions_sha256': sha256(run_folder / 'predictions_test.parquet'),
        'anti_lookahead_reference': spec['anti_lookahead_reference'],
        'scores_are_not_returns': True, 'no_portfolio_pnl_without_explicit_return_or_execution_contract': True}

"""Physical UTC plus operator-approved event order. No timestamp arithmetic."""
from enum import IntEnum
import numpy as np
import pandas as pd
from .data_adapter import SOURCE_COLUMNS, NUMERIC_COLUMNS, validate_source_frame

VERSION = 'CAUSAL_EVENT_CLOCK_V1'


class Phase(IntEnum):
    BAR_CLOSE = 10
    DECISION = 20
    NEXT_BAR_OPEN = 30


class CausalContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CausalContractError(message)


def event_key(timestamp, phase):
    stamp = pd.Timestamp(timestamp)
    require(not pd.isna(stamp) and str(stamp.tz) == 'UTC', 'UTC_AWARE_EVENT_REQUIRED')
    require(type(phase) is int or isinstance(phase, Phase), 'EVENT_PHASE_INTEGER_REQUIRED')
    require(int(phase) in (10, 20, 30), 'UNKNOWN_EVENT_PHASE')
    return stamp, int(phase)


def event_json(key):
    return {'timestamp_utc': key[0].isoformat(), 'event_phase': key[1]}


def validate_bars(frame):
    require(len(frame) > 0 and frame.index.equals(pd.RangeIndex(len(frame))), 'ORDERED_RANGE_INDEX_REQUIRED')
    required = ['datetime_utc', 'instrument', 'timeframe', 'price_basis', 'bar_start_utc', 'bar_end_utc',
                'open', 'high', 'low', 'close', *NUMERIC_COLUMNS, 'source_m1_count', 'has_internal_gap']
    require(set(required) <= set(frame.columns), 'CANONICAL_COLUMNS_REQUIRED')
    for column in ('instrument', 'timeframe', 'price_basis'):
        require(frame[column].notna().all() and frame[column].nunique() == 1, 'SINGLE_ASSET_IDENTITY_REQUIRED:' + column)
    side = frame.price_basis.iloc[0]
    require(side in ('BID', 'ASK'), 'EXPLICIT_BID_OR_ASK_REQUIRED')
    raw = frame.rename(columns={'datetime_utc': 'timestamp_utc'})[list(SOURCE_COLUMNS)].copy()
    validate_source_frame(raw, frame.timeframe.iloc[0])
    for column in ('open', 'high', 'low', 'close'):
        require(frame[column].dtype == np.dtype('float64'), 'FLOAT64_PRICE_REQUIRED')
        require(frame[column].equals(frame[f'{side.lower()}_{column}']), 'CANONICAL_SIDE_PARITY_REQUIRED')
        require((frame[column] > 0).all(), 'POSITIVE_PRICE_REQUIRED_FOR_RATIOS')
    # Source validation already proves unique UTC bounds, strict order, no overlap.
    for close, decision, opening in zip(frame.bar_end_utc.iloc[:-1], frame.bar_end_utc.iloc[:-1], frame.bar_start_utc.iloc[1:]):
        require(event_key(close, Phase.BAR_CLOSE) < event_key(decision, Phase.DECISION)
                < event_key(opening, Phase.NEXT_BAR_OPEN), 'REVERSED_CAUSAL_TRANSITION')


def observation_events(frame):
    validate_bars(frame)
    result = pd.DataFrame(index=frame.index.copy())
    result.index.name = 'row_id'
    result['decision_time'] = frame.bar_end_utc.copy()
    result['decision_phase'] = int(Phase.DECISION)
    result['feature_cutoff_time'] = frame.bar_end_utc.copy()
    result['feature_cutoff_phase'] = int(Phase.BAR_CLOSE)
    return result

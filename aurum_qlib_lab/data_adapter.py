"""AURUM certified Parquet -> canonical DataFrame -> Qlib StaticDataLoader.

Only read-only source handles are used. No sorting, filling, resampling or MID
construction. Original labels and interval bounds are preserved exactly.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

CONTRACT_VERSION = 'AURUM_QLIB_DATA_CONTRACT_V1'
IMPLEMENTATION_VERSION = 'AURUM_QLIB_DATA_ADAPTER_V1.0'
PRICE_BASIS_DEFINITION_VERSION = 'AURUM_SOURCE_SIDE_OHLCV_V1'
MISSING_POLICY_VERSION = 'REJECT_NULL_NONFINITE_KEEP_SOURCE_GAPS_V1'
SIDES = ('BID', 'ASK')
TIMEFRAME_SECONDS = {'M1':60,'M5':300,'M10':600,'M15':900,'M30':1800,'H1':3600,'H4':14400,'D1':86400,'W1':604800}
TIME_COLUMNS = ('timestamp_utc','bar_start_utc','bar_end_utc')
NUMERIC_COLUMNS = tuple(f'{side}_{field}' for side in ('bid','ask') for field in ('open','high','low','close','volume'))
SOURCE_COLUMNS = (*TIME_COLUMNS,*NUMERIC_COLUMNS,'source_m1_count','has_internal_gap')
SOURCE_SCHEMA = pa.schema([
    *(pa.field(c,pa.timestamp('us',tz='UTC'),nullable=False) for c in TIME_COLUMNS),
    *(pa.field(c,pa.float64(),nullable=False) for c in NUMERIC_COLUMNS),
    pa.field('source_m1_count',pa.int32(),nullable=False),
    pa.field('has_internal_gap',pa.bool_(),nullable=False),
])

class DataContractError(ValueError):
    """Admission fails closed; certified source is never repaired."""

def source_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataContractError(message)

def _inside(path: Path, root: Path) -> Path:
    resolved=path.resolve()
    _require(resolved.is_relative_to(root.resolve()),'SOURCE_PATH_ESCAPE')
    return resolved

def validate_source_frame(raw: pd.DataFrame, timeframe: str) -> None:
    """Validation only. Reject malformed rows; do not move or repair any values."""
    _require(timeframe in TIMEFRAME_SECONDS,'UNSUPPORTED_TIMEFRAME')
    _require(list(raw.columns)==list(SOURCE_COLUMNS),'SOURCE_COLUMNS_MISMATCH')
    _require(len(raw)>0,'EMPTY_SOURCE')
    _require(raw.index.equals(pd.RangeIndex(len(raw))),'NONCANONICAL_ROW_INDEX')
    _require(not raw.isna().any().any(),'SOURCE_NULL_NOT_ALLOWED')
    for name in TIME_COLUMNS:
        dtype=raw[name].dtype
        _require(isinstance(dtype,pd.DatetimeTZDtype) and str(dtype.tz)=='UTC','UTC_AWARE_REQUIRED:'+name)
        _require(raw[name].is_unique,'DUPLICATE_TIMESTAMP:'+name)
        _require(raw[name].is_monotonic_increasing,'STRICT_TEMPORAL_ORDER_REQUIRED:'+name)
    duration=raw.bar_end_utc-raw.bar_start_utc
    _require((duration==pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe])).all(),'INTERVAL_DURATION_MISMATCH')
    expected_label=raw.bar_start_utc if timeframe=='M1' else raw.bar_end_utc
    _require(raw.timestamp_utc.equals(expected_label),'SOURCE_TIMESTAMP_LABEL_MISMATCH')
    _require((raw.bar_start_utc.iloc[1:].to_numpy()>=raw.bar_end_utc.iloc[:-1].to_numpy()).all(),'OVERLAPPING_INTERVALS')
    for name in NUMERIC_COLUMNS:
        _require(raw[name].dtype==np.dtype('float64'),'FLOAT64_REQUIRED:'+name)
    _require(np.isfinite(raw[list(NUMERIC_COLUMNS)].to_numpy()).all(),'NONFINITE_SOURCE')
    for side in ('bid','ask'):
        o,h,l,c,v=(raw[f'{side}_{field}'] for field in ('open','high','low','close','volume'))
        _require(((h>=o)&(h>=c)&(l<=o)&(l<=c)&(h>=l)).all(),'OHLC_INCONSISTENT:'+side)
        _require((v>=0).all(),'NEGATIVE_VOLUME:'+side)
    _require(raw.source_m1_count.dtype==np.dtype('int32'),'SOURCE_COUNT_INT32_REQUIRED')
    _require(raw.has_internal_gap.dtype==np.dtype('bool'),'GAP_FLAG_BOOL_REQUIRED')
    _require(((raw.source_m1_count>=1)&(raw.source_m1_count<=TIMEFRAME_SECONDS[timeframe]//60)).all(),'SOURCE_COUNT_INVALID')

def _canonical_frame(raw: pd.DataFrame, *, instrument: str, timeframe: str,
                     price_basis: Literal['BID','ASK'], generation: str,
                     source_path: str, source_hash: str) -> pd.DataFrame:
    _require(price_basis in SIDES,'PRICE_BASIS_REQUIRED_BID_OR_ASK; MID_NOT_CERTIFIED')
    validate_source_frame(raw,timeframe)
    side=price_basis.lower()
    result=pd.DataFrame({'datetime_utc':raw.timestamp_utc.copy(),
                         'instrument':instrument,'timeframe':timeframe,'price_basis':price_basis,
                         **{field:raw[f'{side}_{field}'].copy() for field in ('open','high','low','close','volume')},
                         'data_generation':generation,'source_path':source_path,'source_sha256':source_hash,
                         'bar_start_utc':raw.bar_start_utc.copy(),'bar_end_utc':raw.bar_end_utc.copy(),
                         **{name:raw[name].copy() for name in (*NUMERIC_COLUMNS,'source_m1_count','has_internal_gap')}})
    _require(len(result)==len(raw),'ROW_PARITY_FAILURE')
    return result

@dataclass(frozen=True)
class AdaptedData:
    """Caller receives a DataFrame copy and an explicit portable lineage receipt."""
    frame: pd.DataFrame
    identity: dict

class AurumDataAdapter:
    def __init__(self, data_root: str | Path, *, instrument_map_sha256: str, qualified_manifest_sha256=()):
        self.data_root=Path(data_root).resolve()
        self.clean_root=(self.data_root/'CLEAN_DATA'/'GENERATIONS').resolve()
        self.map_path=self.data_root/'AURUM_JFOREX_INSTRUMENT_MAP_V1.csv'
        self.map_sha256=instrument_map_sha256
        self.qualified_manifest_sha256=frozenset(qualified_manifest_sha256)
        _require(len(instrument_map_sha256)==64,'MAPPING_HASH_REQUIRED')
        _require(source_sha256(self.map_path)==self.map_sha256,'MAPPING_HASH_MISMATCH')
        with self.map_path.open('r',encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        _require(source_sha256(self.map_path)==self.map_sha256,'MAPPING_CHANGED_DURING_READ')
        _require(len(rows)>0,'EMPTY_MAPPING')
        _require(len({r['aurum_symbol'] for r in rows})==len(rows),'DUPLICATE_CANONICAL_SYMBOL')
        self.mapping={r['aurum_symbol']:r for r in rows}

    def load(self, instrument: str, timeframe: str, *, price_basis: Literal['BID','ASK']) -> AdaptedData:
        _require(price_basis in SIDES,'PRICE_BASIS_REQUIRED_BID_OR_ASK; MID_NOT_CERTIFIED')
        _require(instrument in self.mapping,'UNKNOWN_CANONICAL_INSTRUMENT')
        _require(source_sha256(self.map_path)==self.map_sha256,'MAPPING_EXTERNAL_DRIFT')
        row=self.mapping[instrument]
        _require(row['status']=='ACTIVE','INSTRUMENT_NOT_ACTIVE')
        _require(row['aurum_symbol']==row['storage_symbol']==instrument,'CANONICAL_SYMBOL_MISMATCH')
        _require(row['timezone']=='UTC' and row['price_sides']=='BID_ASK','SOURCE_MAPPING_CONTRACT_MISMATCH')
        _require(row['data_contract']=='AURUM_JFOREX_BIDASK_TIMEFRAMES_V1','SOURCE_CONTRACT_UNSUPPORTED')
        _require(timeframe in row['timeframes'].split('|') and timeframe in TIMEFRAME_SECONDS,'TIMEFRAME_NOT_AVAILABLE')
        generation=_inside(self.data_root/row['generation_relative_path'],self.clean_root)
        manifest_path=_inside(generation/row['manifest'],generation)
        manifest_hash=source_sha256(manifest_path)
        with manifest_path.open('r',encoding='utf-8-sig') as stream:
            manifest=json.load(stream)
        _require(manifest['generation_id']==row['generation_id'],'GENERATION_ID_MISMATCH')
        _require(manifest['build_state']==manifest['crosscheck_state']=='PASS','SOURCE_NOT_CERTIFIED')
        _require(manifest['timezone']=='UTC' and manifest['price_sides']=='BID_ASK','SOURCE_METADATA_MISMATCH')
        extended=manifest_hash in self.qualified_manifest_sha256
        if extended:
            _require(manifest.get('output_contract_id')=='AURUM_JFOREX_BIDASK_TIMEFRAMES_V1'
                     and manifest.get('status')=='CANDIDATE_9TF_COMPLETE'
                     and manifest.get('candidate_only') is True and manifest.get('official_promotion') is False
                     and manifest.get('production_registered') is False
                     and manifest.get('no_fill_or_interpolation') is True, 'QUALIFIED_MANIFEST_CONTRACT_MISMATCH')
            _require(source_sha256(self.data_root/'TIME_CONTRACT.json')==manifest.get('time_contract_sha256'),
                     'TIME_CONTRACT_HASH_MISMATCH')
        else:
            _require(isinstance(manifest.get('source_generation_id'),str) and bool(manifest['source_generation_id']),
                     'SOURCE_GENERATION_MISSING_REQUIRES_QUALIFICATION')
        records=[r for r in manifest['records'] if r['timeframe']==timeframe]
        _require(len(records)==1,'TIMEFRAME_RECORD_NOT_UNIQUE')
        record=records[0]
        _require(record['asset']==instrument and record['generation_id']==row['generation_id'],'RECORD_IDENTITY_MISMATCH')
        _require(record['build_state']==record['crosscheck_state']=='PASS','TIMEFRAME_NOT_CERTIFIED')
        path=_inside(generation/record['output_path'],generation)
        expected_hash=record['output_hash']
        before_hash=source_sha256(path)
        _require(before_hash==expected_hash,'CERTIFIED_PARQUET_HASH_MISMATCH')
        with path.open('rb') as source:
            parquet=pq.ParquetFile(source)
            schema=parquet.schema_arrow
            exact_schema=schema.equals(SOURCE_SCHEMA,check_metadata=False)
            same_types=(schema.names==SOURCE_SCHEMA.names and
                        all(a.type==b.type for a,b in zip(schema,SOURCE_SCHEMA)))
            _require(exact_schema or (extended and same_types),'SOURCE_ARROW_SCHEMA_MISMATCH')
            _require(parquet.metadata.num_rows==record['row_count'],'MANIFEST_ROW_COUNT_MISMATCH')
            raw=parquet.read(use_threads=False).to_pandas(use_threads=False)
        _require(source_sha256(path)==before_hash,'SOURCE_CHANGED_DURING_READ')
        _require(source_sha256(manifest_path)==manifest_hash,'MANIFEST_CHANGED_DURING_READ')
        _require(source_sha256(self.map_path)==self.map_sha256,'MAPPING_CHANGED_DURING_LOAD')
        frame=_canonical_frame(raw,instrument=instrument,timeframe=timeframe,price_basis=price_basis,
                               generation=row['generation_id'],source_path=str(path),source_hash=before_hash)
        identity={'contract_version':CONTRACT_VERSION,'adapter_version':IMPLEMENTATION_VERSION,
                  'instrument':instrument,'provider_symbol':row['provider_symbol'],'timeframe':timeframe,
                  'price_basis':price_basis,'price_basis_definition_version':PRICE_BASIS_DEFINITION_VERSION,
                  'data_generation':row['generation_id'],'source_generation_id':manifest.get('source_generation_id'),
                  'source_path':str(path),'source_sha256':before_hash,'source_hash_before_after_equal':True,
                  'instrument_map_sha256':self.map_sha256,'generation_manifest_path':str(manifest_path),
                  'generation_manifest_sha256':manifest_hash,'row_count':len(frame),
                  'start_utc':frame.datetime_utc.iloc[0].isoformat(),'end_utc':frame.datetime_utc.iloc[-1].isoformat(),
                  'timestamp_label':'INTERVAL_START' if timeframe=='M1' else 'INTERVAL_END',
                  'closed_bar_reference':'bar_end_utc; source label is preserved, not a decision-time substitute',
                  'historical_available_at':'UNKNOWN_IN_SOURCE_CONTRACT',
                  'missing_data_policy_version':MISSING_POLICY_VERSION,
                  'volume_policy':'Preserve selected side reported volume; export units not certified; zero is a real preserved value',
                  'gap_policy':'Preserve existing rows and diagnostic flags; no artificial bars or fill',
                  'row_policy':'PRESERVE_ORDER_AND_COUNT; REJECT_INVALID_INPUT',
                  'source_read_only':True,'no_resampling':True,'no_forward_fill':True,'no_backfill':True}
        if extended:
            identity['source_provenance']={
                'source_generation_status':'NOT_PROVIDED_BY_SOURCE_MANIFEST',
                'source_m1_hash':manifest['source_m1_hash'],
                'source_versions':manifest['source_versions'],
                'time_contract_sha256':manifest['time_contract_sha256'],
                'technical_admission':'ISOLATED_PRISM_QUALIFICATION',
                **{k:manifest[k] for k in ('candidate_only','production_registered','official_promotion','economic_scientific_admission')}}
        return AdaptedData(frame,identity)

def to_qlib_frame(adapted: AdaptedData) -> pd.DataFrame:
    """Use the verified StaticDataLoader DataFrame path; no binary datastore."""
    frame=adapted.frame
    identity=adapted.identity
    _require(len(frame)==identity['row_count'],'CANONICAL_FRAME_ROW_COUNT_MISMATCH')
    for column,key in (('instrument','instrument'),('timeframe','timeframe'),('price_basis','price_basis'),
                       ('source_sha256','source_sha256'),('data_generation','data_generation')):
        _require(frame[column].eq(identity[key]).all(),'CANONICAL_IDENTITY_MISMATCH:'+column)
    _require(frame.datetime_utc.is_unique and frame.datetime_utc.is_monotonic_increasing,'CANONICAL_TIME_ORDER_INVALID')
    _require(str(frame.datetime_utc.dt.tz)=='UTC','CANONICAL_UTC_REQUIRED')
    result=frame[['open','high','low','close','volume']].copy()
    result.index=pd.MultiIndex.from_arrays([frame.datetime_utc,frame.instrument],names=['datetime','instrument'])
    _require(result.index.is_unique and result.index.is_monotonic_increasing,'QLIB_INDEX_INVALID')
    result.columns=pd.MultiIndex.from_product([['feature'],list(result.columns)])
    return result

def qlib_static_load(adapted: AdaptedData) -> pd.DataFrame:
    from qlib.data.dataset.loader import StaticDataLoader
    expected=to_qlib_frame(adapted)
    actual=StaticDataLoader(config=expected).load(instruments=[adapted.identity['instrument']],
                                               start_time=expected.index[0][0],end_time=expected.index[-1][0])
    pd.testing.assert_frame_equal(actual,expected,check_exact=True)
    return actual

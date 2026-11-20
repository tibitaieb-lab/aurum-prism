"""Three declared synthetic strategy series, never substitutes for market data."""
import json
import numpy as np
import pandas as pd
from aurum_qlib_lab.strategy_series import stamp_payload_hashes

ASSETS = ('DEMO_AZUR', 'DEMO_CORAIL', 'DEMO_JADE')
STRATEGIES = tuple('FIXTURE_' + asset for asset in ASSETS)
SEED = 5051729


def return_fixture(observations=240):
    rng = np.random.default_rng(SEED)
    common = rng.normal(0, 0.004, observations)
    noises = rng.normal(0, 1, (observations, 3))
    values = 0.0001 + common[:, None] + noises * np.array([0.006, 0.010, 0.008])
    times = pd.date_range('2024-01-01T04:00:00Z', periods=observations, freq='4h')
    provenance = json.dumps({'kind': 'SYNTHETIC_CERTIFICATION_FIXTURE_V1', 'seed': SEED, 'observations': observations,
                             'reporting_currency_policy': 'Synthetic common NAV units, no physical FX/market price conversion',
                             'NOT_FOR_RESEARCH_CONCLUSIONS': True}, sort_keys=True)
    rows = []
    for i, timestamp in enumerate(times):
        for j, asset in enumerate(ASSETS):
            rows.append({'timestamp_utc': timestamp, 'interval_start_utc': timestamp - pd.Timedelta(hours=4),
                         'available_at_utc': timestamp, 'available_phase': 10, 'strategy_id': STRATEGIES[j],
                         'asset': asset, 'timeframe': 'H4', 'return': float(values[i, j]),
                         'source_run_id': 'PRISM_PUBLIC_SYNTHETIC_PORTFOLIO_V1', 'cost_status': 'GROSS_SOURCE_COSTS',
                         'reporting_currency': 'SYNTHETIC_COMMON_NAV_UNITS', 'provenance': provenance})
    return stamp_payload_hashes(pd.DataFrame(rows))

"""Small causal allocation lab: manual, equal and historical inverse volatility."""
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .event_clock import event_key, event_json, require
from .strategy_series import validate_return_series, load_oos_scores
from .certification_gate import require_certified, certificate_path
from .experiment_store import read_json, sha256, atomic_json

VERSION = 'AURUM_PORTFOLIO_LAB_V1'
NATIVE_METHODS = ('MANUAL', 'EQUAL_WEIGHT', 'INVERSE_VOLATILITY')
METHODS = (*NATIVE_METHODS, 'MINIMUM_VARIANCE', 'MEAN_VARIANCE', 'RISK_PARITY')
CRITICAL = ('TIME_ALIGNMENT', 'PORTFOLIO_CLOCK_CAUSALITY', 'PORTFOLIO_FUTURE_MUTATION_TEST',
            'PORTFOLIO_TRUNCATED_HISTORY_TEST', 'MISSING_DATA_POLICY', 'MANUAL_WEIGHTS', 'EQUAL_WEIGHT',
            'INVERSE_VOLATILITY', 'CONSTRAINTS', 'REBALANCING', 'COST_POLICY', 'METRIC_DEFINITIONS', 'QLIB_SCORE_ISOLATION')


@dataclass(frozen=True)
class PortfolioConfig:
    method: str
    historical_window: int = 24
    rebalance_every_observations: int = 8
    cash_weight: float = 0.1
    min_weight: float = 0.0
    max_weight: float = 0.8
    max_positions: int = 3
    cost_rate: float = 0.001
    manual_weights: dict | None = None
    covariance_estimator: str = 'EMPIRICAL'
    shrinkage_alpha: float = 0.1
    risk_aversion: float = 1.0
    risk_periods_per_year: int | None = None
    risk_frequency_note: str | None = None


def validate_config(config):
    require(config.method in METHODS, 'UNSUPPORTED_PORTFOLIO_METHOD')
    from .quantitative import validate_quant_options
    validate_quant_options(config)
    require(type(config.historical_window) is int and config.historical_window >= 2, 'MINIMUM_TWO_PAST_OBSERVATIONS_REQUIRED')
    require(type(config.rebalance_every_observations) is int and config.rebalance_every_observations >= 1, 'INVALID_REBALANCE_FREQUENCY')
    from .portfolio_capacity import validate_position_limit
    validate_position_limit(config.max_positions)
    values = [config.cash_weight, config.min_weight, config.max_weight, config.cost_rate]
    require(all(type(x) in (int, float) and np.isfinite(x) for x in values), 'FINITE_PORTFOLIO_PARAMETERS_REQUIRED')
    require(0 <= config.cash_weight <= 1 and 0 <= config.min_weight <= config.max_weight <= 1
            and 0 <= config.cost_rate < 1, 'LONG_ONLY_BOUNDS_OR_COST_RATE_INVALID')
    require(config.method == 'MANUAL' or config.manual_weights is None, 'MANUAL_WEIGHTS_ONLY_FOR_MANUAL_METHOD')


def check_weights(weights, cash, config):
    weights = np.asarray(weights, dtype=np.float64)
    require(np.isfinite(weights).all() and (weights >= 0).all() and 0 <= cash <= 1, 'FINITE_LONG_ONLY_WEIGHTS_REQUIRED')
    require(abs(float(weights.sum()) + cash - 1) <= 1e-12, 'WEIGHTS_PLUS_CASH_MUST_SUM_TO_ONE')
    active = weights > 0
    require(int(active.sum()) <= config.max_positions, 'MAX_POSITIONS_EXCEEDED')
    require((weights[active] >= config.min_weight - 1e-12).all()
            and (weights[active] <= config.max_weight + 1e-12).all(), 'REBALANCE_WEIGHT_BOUNDS_EXCEEDED')


def _allocate(ids, config, volatility=None):
    validate_config(config)
    require(config.method in NATIVE_METHODS,'QUANT_METHOD_REQUIRES_COVARIANCE_PATH')
    if config.method == 'MANUAL':
        require(isinstance(config.manual_weights, dict) and set(config.manual_weights) == set(ids), 'EXPLICIT_MANUAL_UNIVERSE_REQUIRED')
        require(all(type(v) in (int, float) for v in config.manual_weights.values()), 'NUMERIC_MANUAL_WEIGHTS_REQUIRED')
        weights = np.asarray([config.manual_weights[x] for x in ids], dtype=np.float64)
    elif config.method == 'EQUAL_WEIGHT':
        weights = np.full(len(ids), (1 - config.cash_weight) / len(ids))
    else:
        require(volatility is not None and np.isfinite(volatility).all() and (volatility > 0).all(), 'POSITIVE_PAST_VOLATILITY_REQUIRED')
        inverse = 1 / volatility
        weights = (1 - config.cash_weight) * inverse / inverse.sum()
    check_weights(weights, config.cash_weight, config)
    return weights


def weights_at(frame, config, decision_time, canonical_assets):
    """Future rows may exist physically but cannot enter the historical window."""
    validate_config(config)
    matrix = validate_return_series(frame, canonical_assets)
    decision = event_key(decision_time, 20)
    cutoff = event_key(decision_time, 10)
    require(decision[0] in matrix.index, 'REBALANCE_MUST_BE_REAL_VALUATION_TIMESTAMP')
    historical = matrix.loc[matrix.index <= cutoff[0]].tail(config.historical_window)
    require(len(historical) == config.historical_window, 'INSUFFICIENT_PAST_HISTORY')
    available = frame.loc[frame.timestamp_utc.isin(historical.index)]
    require(all(event_key(t, int(p)) <= cutoff for t, p in zip(available.available_at_utc, available.available_phase)),
            'REBALANCE_INFORMATION_NOT_YET_AVAILABLE')
    require(historical.index[-1] == decision[0], 'MISSING_LATEST_REBALANCE_INFORMATION')
    ids = list(historical.columns)
    values = historical.to_numpy(dtype=np.float64)
    volatility = values.std(axis=0, ddof=1)
    quantitative=None
    if config.method in NATIVE_METHODS:
        weights = _allocate(ids, config, volatility)
    else:
        from .quantitative import quantitative_weights
        weights,quantitative=quantitative_weights(values,config)
        check_weights(weights,config.cash_weight,config)
    covariance = historical.cov(ddof=1).to_numpy()
    correlation = historical.corr().to_numpy()
    hash_input = json.dumps({'ids': ids, 'timestamps': [t.isoformat() for t in historical.index]}, sort_keys=True).encode()
    history_hash = hashlib.sha256(hash_input + np.asarray(values, dtype='<f8').tobytes()).hexdigest()
    receipt = {'rebalance_decision_event': event_json(decision), 'information_cutoff_event': event_json(cutoff),
               'execution_event': event_json(event_key(decision[0], 30)),
               'window_start_utc': historical.index[0].isoformat(), 'window_end_utc': historical.index[-1].isoformat(),
               'historical_observations': len(historical), 'history_values_sha256': history_hash,
               'weights': {x: float(w) for x, w in zip(ids, weights)}, 'cash_weight': config.cash_weight,
               'volatility_per_observation': dict(zip(ids, volatility.tolist())),
               'covariance': covariance.tolist(), 'correlation': [[None if not np.isfinite(x) else float(x) for x in row] for row in correlation],
               'matrix_order': ids, 'method': config.method,
               'objective': 'Explicit manual allocation' if config.method == 'MANUAL' else 'Equal capital among supplied series' if config.method == 'EQUAL_WEIGHT'
                            else 'Heuristic equalization of standalone historical volatility contributions; not a global optimum',
               'bounds_scope': 'At rebalance; actual held weights drift between rebalances',
               'annualization_policy': 'NONE; observed-period metrics only', 'cash_return_policy': 'ZERO',
               'missing_policy': 'STRICT_COMMON_GRID_AND_AVAILABILITY_FAIL_CLOSED', 'config': asdict(config)}
    if quantitative is not None:
        receipt['quantitative']=quantitative
        receipt['objective']=quantitative.get('objective_definition','ALL_CASH_NO_RISK_ALLOCATION')
    return weights, receipt


def weights_from_scores(scores, config, decision_time):
    """Weights-only use of OOS score context. No scores-as-returns conversion."""
    validate_config(config)
    require(config.method in ('MANUAL', 'EQUAL_WEIGHT'), 'INVERSE_VOLATILITY_REQUIRES_REALIZED_RETURN_SERIES')
    cutoff = event_key(decision_time, 20)
    require(not scores.empty and np.isfinite(scores.prediction).all(), 'FINITE_OOS_SCORE_CONTEXT_REQUIRED')
    eligible = scores.loc[[event_key(t, int(p)) <= cutoff for t, p in zip(scores.decision_time, scores.decision_phase)]]
    require(len(eligible) > 0, 'NO_SCORE_AVAILABLE_AT_REBALANCE')
    latest = eligible.groupby('instrument', sort=True).tail(1)
    ids = sorted(set(scores.instrument))
    require(set(latest.instrument) == set(ids) and latest.decision_time.nunique() == 1
            and latest.decision_time.iloc[0] == cutoff[0], 'SYNCHRONOUS_CURRENT_OOS_SCORES_REQUIRED_NO_FILL')
    weights = _allocate(ids, config)
    return {'family': 'QLIB_OOS_SCORES', 'decision_event': event_json(cutoff),
            'information_cutoff_event': event_json(cutoff), 'execution_event': event_json(event_key(cutoff[0], 30)),
            'weights': dict(zip(ids, weights.tolist())), 'cash_weight': config.cash_weight,
            'scores': dict(zip(latest.instrument, latest.prediction.astype(float))),
            'score_magnitude_usage': 'Context only; MANUAL/EQUAL_WEIGHT do not transform score magnitude into a trading strategy',
            'return_metrics': 'NOT_APPLICABLE_WEIGHTS_ONLY', 'config': asdict(config)}


def validate_valuation_availability(frame, first_valuation):
    # This engine publishes NAV at each return endpoint, phase10 (then costs phase30).
    # Delayed publications need a distinct valuation clock, which is not implemented.
    used = frame.loc[frame.timestamp_utc >= first_valuation]
    require((used.available_at_utc <= used.timestamp_utc).all(),
            'PORTFOLIO_VALUATION_PUBLICATION_DELAY_UNSUPPORTED')


def simulate_certification(frame, config, canonical_assets, portfolio_id):
    """Uncertified execution reserved for local fixture certification, never the UI entry point."""
    validate_config(config)
    matrix = validate_return_series(frame, canonical_assets)
    require(len(matrix) > config.historical_window, 'NO_POST_WARMUP_PORTFOLIO_INTERVAL')
    ids, start = list(matrix.columns), config.historical_window - 1
    validate_valuation_availability(frame, matrix.index[start])
    asset_values, cash, previous_equity = np.zeros(len(ids)), 1.0, 1.0
    rows, decisions = [], []
    for position in range(start, len(matrix)):
        timestamp = matrix.index[position]
        if position > start:
            asset_values *= 1 + matrix.iloc[position].to_numpy()
        before_cost = float(asset_values.sum() + cash)
        gross_return = before_cost / previous_equity - 1
        rebalance = (position - start) % config.rebalance_every_observations == 0 and position < len(matrix) - 1
        cost, turnover = 0.0, 0.0
        if rebalance:
            target, receipt = weights_at(frame, config, timestamp, canonical_assets)
            preweights = asset_values / before_cost
            turnover = float(np.abs(target - preweights).sum())
            cost = before_cost * config.cost_rate * turnover
            require(cost < before_cost, 'COST_EXHAUSTS_EQUITY')
            after_cost = before_cost - cost
            asset_values = after_cost * target
            cash = after_cost * config.cash_weight
            receipt.update(portfolio_id=portfolio_id, turnover_risky_l1=turnover, cost_amount=cost,
                           equity_before_cost=before_cost, equity_after_cost=after_cost)
            decisions.append(receipt)
        equity = float(asset_values.sum() + cash)
        require(np.isfinite(equity) and equity > 0, 'PORTFOLIO_EQUITY_INVALID')
        row = {'timestamp_utc': timestamp, 'portfolio_id': portfolio_id, 'portfolio_return': equity / previous_equity - 1,
               'gross_period_return': gross_return, 'equity_before_cost': before_cost, 'equity': equity,
               'cost_amount': cost, 'turnover_risky_l1': turnover, 'rebalance': rebalance,
               'valuation_event_phase': 30 if rebalance else 10, 'cash_weight_actual': cash / equity}
        row.update({'weight_' + strategy: float(value / equity) for strategy, value in zip(ids, asset_values)})
        rows.append(row)
        previous_equity = equity
    output = pd.DataFrame(rows)
    peaks = np.maximum.accumulate(np.maximum(output.equity.to_numpy(), 1.0))
    output['drawdown'] = output.equity.to_numpy() / peaks - 1
    metrics = {'cumulative_return': float(output.equity.iloc[-1] - 1), 'max_drawdown': float(output.drawdown.min()),
               'volatility_per_observation': float(output.portfolio_return.std(ddof=1)),
               'turnover_risky_l1_total': float(output.turnover_risky_l1.sum()), 'costs_total_initial_nav_units': float(output.cost_amount.sum()),
               'initial_equity': 1.0, 'final_equity': float(output.equity.iloc[-1]), 'valuation_observations': len(output),
               'rebalance_count': len(decisions), 'correlation': decisions[-1]['correlation'], 'covariance': decisions[-1]['covariance'],
               'matrix_order': ids, 'risk_matrix_scope': 'Last allocation past-only historical window, not future allocation information',
               'annualization_policy': 'NONE', 'sharpe': 'NOT_IMPLEMENTED_NO_ANNUALIZATION_OR_SHARPE_RISK_FREE_POLICY',
               'source_cost_status': frame.cost_status.iloc[0], 'reporting_currency': frame.reporting_currency.iloc[0],
               'cash_return_policy': 'ZERO', 'purpose': 'SMOKE_ONLY_NOT_FOR_RESEARCH_CONCLUSIONS', 'config': asdict(config)}
    if config.risk_periods_per_year is not None:
        from .quantitative import qlib_risk_analysis
        metrics['qlib_risk_analysis']=qlib_risk_analysis(output.portfolio_return,
                                  config.risk_periods_per_year,config.risk_frequency_note)
    return output, decisions, metrics


def require_portfolio_certified(project):
    project = Path(project)
    require_certified(project)
    master = read_json(project / 'MASTER_STATE.json')
    try:
        path = certificate_path(project,'portfolio')
        require(master.get('portfolio_lookahead_certified') is True and path.is_file(), 'PORTFOLIO_CERTIFICATION_ABSENT')
        cert = read_json(path)
        require(cert['FINAL_VERDICT'] == 'PASS' and all(cert.get(k) == 'PASS' for k in CRITICAL), 'PORTFOLIO_CERTIFICATION_NOT_PASS')
        require(sha256(path) == master.get('portfolio_certification_sha256'), 'PORTFOLIO_CERTIFICATION_HASH_INVALID')
        require(isinstance(cert.get('code_hashes'), dict) and len(cert['code_hashes']) > 0, 'PORTFOLIO_CODE_HASHES_REQUIRED')
        for name, value in cert['code_hashes'].items():
            component = (project / name).resolve()
            require(component.is_relative_to(project.resolve()) and sha256(component) == value, 'PORTFOLIO_CODE_DRIFT')
        return cert
    except (ValueError, OSError, TypeError) as error:
        master.update(portfolio_lookahead_certified=False, portfolio_certification_invalidated=True,
                      portfolio_invalidation_reason=str(error))
        atomic_json(project / 'MASTER_STATE.json', master)
        raise


def run_portfolio(project, frame, config, canonical_assets, portfolio_id):
    cert = require_portfolio_certified(project)
    require(set(frame.asset) <= set(cert['canonical_symbols']), 'UNKNOWN_CERTIFIED_PORTFOLIO_ASSET')
    return simulate_certification(frame, config, canonical_assets, portfolio_id)


def run_score_portfolio(project, run_folder, config, decision_time, canonical_assets):
    cert = require_portfolio_certified(project)
    scores, provenance = load_oos_scores(run_folder, canonical_assets)
    require(set(scores.instrument) <= set(cert['canonical_symbols']), 'UNKNOWN_CERTIFIED_PORTFOLIO_ASSET')
    master = read_json(Path(project) / 'MASTER_STATE.json')
    require(provenance['anti_lookahead_reference']['sha256'] == master['anti_lookahead_certification_sha256'], 'SCORE_CERTIFICATION_REFERENCE_CHANGED')
    allocation = weights_from_scores(scores, config, decision_time)
    allocation['source_provenance'] = provenance
    return allocation

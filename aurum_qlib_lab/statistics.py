"""Explicit retrospective statistics; never an allocation input or an ARL admission."""
import hashlib
import json
import math
import numpy as np
import pandas as pd
from scipy import stats
from scipy.integrate import quad

VERSION = 'PRISM_STATISTICS_D_V1'
SOURCE = 'https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf'

def unavailable(reason):
    return {'status': 'NON_CALCULABLE', 'value': None, 'reason': reason}

def observed(value, **extra):
    return {'status': 'CALCULABLE', 'value': float(value), **extra}

def _text(value):
    if not isinstance(value,str) or not 0 < len(value.strip()) <= 1000 or value.strip().lower() in ('none','null','nan','unknown'):
        return False
    try: value.encode('utf-8')
    except UnicodeEncodeError: return False
    return True

def _utc(value):
    try: t = pd.Timestamp(value)
    except (TypeError,ValueError,OverflowError) as error:
        raise ValueError('STATISTICS_EXPLICIT_UTC_REQUIRED') from error
    if pd.isna(t) or t.tzinfo is None or t.utcoffset().total_seconds() != 0:
        raise ValueError('STATISTICS_EXPLICIT_UTC_REQUIRED')
    return t.tz_convert('UTC')

def _number(x):
    return type(x) in (float, int) and np.isfinite(x)

def temporal_diagnostics(values):
    """Ljung-Box on excess returns AND squared centred excess returns, no IID proof."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 30:
        return {'status': 'INSUFFICIENT_SAMPLE', 'minimum_observations': 30,
                'note': 'Asymptotic screening floor; 30 observations do not prove validity'}
    lag = min(10, n // 5)
    tests = {}
    for label, v in [('returns', x), ('squared_centred_returns', (x-x.mean())**2)]:
        v = v-v.mean(); denominator = float(v @ v)
        if denominator <= 0:
            return {'status': 'DEGENERATE_DEPENDENCE_DIAGNOSTIC', 'series': label}
        rho = np.array([float(v[k:] @ v[:-k])/denominator for k in range(1, lag+1)])
        q = n*(n+2)*float(np.sum(rho*rho/(n-np.arange(1,lag+1))))
        tests[label] = {'Q': q, 'lags': lag, 'p_value': float(stats.chi2.sf(q,lag))}
    rejected = any(t['p_value'] < .01 for t in tests.values())
    return {'status': 'DEPENDENCE_DETECTED' if rejected else 'NOT_REJECTED_NOT_PROVEN_IID',
            'significance': .01, 'tests': tests, 'note': 'No stationarity or independence certification'}

def expected_maximum_normal(n_effective):
    """E[max of N standard normals]; fractional N uses CDF Phi(z)**N.
    Numerical order-statistic integral replaces the paper's large-N approximation.
    This keeps the N=1 and N=2 limits coherent without arbitrary clipping.
    """
    if not _number(n_effective) or not 1 <= n_effective <= 1_000_000:
        raise ValueError('EFFECTIVE_TRIALS_OUTSIDE_SUPPORTED_NUMERICAL_DOMAIN')
    if n_effective == 1:
        return 0.0
    def integrand(z):
        return z * math.exp(math.log(n_effective)+stats.norm.logpdf(z)
                            +(n_effective-1)*stats.norm.logcdf(z))
    answer, error = quad(integrand, -12, 12, epsabs=1e-10, epsrel=1e-10, limit=200)
    if not np.isfinite([answer,error]).all() or error > 1e-7:
        raise ValueError('EXPECTED_MAXIMUM_INTEGRATION_UNSTABLE')
    return float(answer)

def selection_parameters(selection, excess, context_id):
    """No automatic counting of jobs/backtests. Completeness is a supplied assertion."""
    if not isinstance(selection, dict):
        return None, 'SELECTION_HISTORY_OR_PARAMETERS_MISSING'
    if selection.get('history_complete') is not True or not _text(selection.get('evidence')):
        return None, 'COMPLETE_SELECTION_HISTORY_EVIDENCE_REQUIRED'
    if selection.get('context_id') != context_id:
        return None, 'TRIAL_FREQUENCY_CURRENCY_RF_HORIZON_CONTEXT_MISMATCH'
    mode = selection.get('mode')
    if mode == 'MANUAL':
        n, variance = selection.get('effective_trials'), selection.get('sharpe_variance')
        if not _number(n) or not 1 <= n <= 1_000_000:
            return None, 'JUSTIFIED_EFFECTIVE_TRIAL_COUNT_REQUIRED'
        if not _number(variance) or variance < 0 or (n > 1 and variance == 0):
            return None, 'POSITIVE_PER_OBSERVATION_TRIAL_SHARPE_VARIANCE_REQUIRED'
        if not _text(selection.get('dependence_justification')):
            return None, 'TRIAL_DEPENDENCE_JUSTIFICATION_REQUIRED'
        return {'effective_trials': float(n), 'sharpe_variance': float(variance),
                'origin': 'FOURNIS_MANUELLEMENT', 'evidence': selection['evidence'],
                'dependence_justification': selection['dependence_justification']}, None
    if mode != 'CORRELATED_TRIAL_RETURNS':
        return None, 'UNSUPPORTED_SELECTION_ESTIMATOR'
    # Matrix consists of excess returns under EXACTLY this context, not annual Sharpes.
    try:
        matrix = np.asarray(selection.get('excess_returns'), dtype=float)
    except (TypeError, ValueError):
        return None, 'INVALID_TRIAL_MATRIX'
    if matrix.ndim != 2 or matrix.shape[0] != len(excess) or matrix.shape[1] < 2:
        return None, 'ALIGNED_COMPLETE_TRIAL_MATRIX_REQUIRED'
    from .portfolio_capacity import validate_capacity
    validate_capacity(matrix.size, matrix.shape[1], decoded_bytes=matrix.nbytes)
    t, m = matrix.shape
    if t <= m or not np.isfinite(matrix).all():
        return None, 'TRIAL_CORRELATION_SAMPLE_INSUFFICIENT_OR_MISSING_VALUES'
    if not any(np.array_equal(matrix[:,i],excess) for i in range(m)):
        return None, 'SELECTED_STRATEGY_ABSENT_FROM_TRIAL_HISTORY'
    if np.max(np.abs(matrix)) > 1e70:
        return None, 'TRIAL_MATRIX_NUMERICAL_RANGE_EXCEEDED'
    sigmas = matrix.std(axis=0,ddof=1)
    if (np.ptp(matrix,axis=0)==0).any() or (sigmas<=0).any():
        return None, 'CONSTANT_TRIAL_RETURNS'
    correlation = np.corrcoef(matrix,rowvar=False)
    if not np.isfinite(sigmas).all() or not np.isfinite(correlation).all():
        return None, 'TRIAL_CORRELATION_NONFINITE'
    rho = float((correlation.sum()-m)/(m*(m-1)))
    if not np.isfinite(rho):
        return None, 'TRIAL_CORRELATION_NONFINITE'
    # Eq.9 appendix A.3; negative average correlation is outside the interpolation.
    if rho < -1e-12 or rho > 1+1e-12:
        return None, 'AVERAGE_CORRELATION_OUTSIDE_HEURISTIC_DOMAIN'
    rho = min(1.0,max(0.0,rho))  # numerical roundoff only
    n = rho + (1-rho)*m
    sharpes = matrix.mean(axis=0)/sigmas
    variance = float(sharpes.var(ddof=1))
    if not np.isfinite(sharpes).all() or not np.isfinite(variance):
        return None, 'TRIAL_SHARPE_DISPERSION_NONFINITE'
    if n > 1+1e-10 and variance <= np.finfo(float).eps:
        return None, 'TRIAL_SHARPE_DISPERSION_NOT_IDENTIFIABLE'
    if abs(n-1) < 1e-10:
        n = 1.0
    return {'effective_trials': n, 'sharpe_variance': variance, 'raw_trials': m,
            'mean_pairwise_correlation': rho, 'origin': 'ESTIMES_EXPLORATOIRES',
            'estimator': 'Bailey-Lopez de Prado appendix A.3 Eq.9: rho+(1-rho)*M',
            'evidence': selection['evidence'],
            'matrix_sha256': hashlib.sha256(np.asarray(matrix,dtype='<f8').tobytes()).hexdigest(),
            'limitations': 'Linear-dependence heuristic; completeness supplied, not independently certified'}, None

def deflated_sharpe(excess, selection, context_id, assumption, justification):
    x = np.asarray(excess,dtype=float)
    n = len(x)
    if n < 30:
        return unavailable('DSR_ASYMPTOTIC_SAMPLE_TOO_SHORT_MINIMUM_30_NOT_SUFFICIENT_FOR_VALIDITY')
    if not np.isfinite(x).all() or np.ptp(x)==0 or x.std(ddof=1)<=0:
        return unavailable('ZERO_VARIANCE_OR_NONFINITE_EXCESS_RETURNS')
    if assumption != 'IID' or not _text(justification):
        return unavailable('IID_STATIONARITY_FINITE_FOURTH_MOMENT_ASSUMPTION_AND_JUSTIFICATION_REQUIRED')
    diagnostics = temporal_diagnostics(x)
    if diagnostics['status'] != 'NOT_REJECTED_NOT_PROVEN_IID':
        return dict(unavailable('TEMPORAL_DEPENDENCE_OR_DEGENERATE_DIAGNOSTICS'), diagnostics=diagnostics)
    parameters, error = selection_parameters(selection,x,context_id)
    if error:
        return unavailable(error)
    centred = x-x.mean(); m2 = float(np.mean(centred**2))
    skew = float(np.mean((centred/math.sqrt(m2))**3))
    kurtosis = float(np.mean((centred/math.sqrt(m2))**4))  # Pearson, Gaussian=3
    sr = float(x.mean()/x.std(ddof=1))
    denominator = 1-skew*sr+(kurtosis-1)*sr*sr/4
    if not np.isfinite(denominator) or denominator <= 0:
        return unavailable('PSR_ASYMPTOTIC_VARIANCE_NONPOSITIVE')
    threshold = math.sqrt(parameters['sharpe_variance'])*expected_maximum_normal(parameters['effective_trials'])
    z = (sr-threshold)*math.sqrt(n-1)/math.sqrt(denominator)
    probability = float(stats.norm.cdf(z))
    return {'status': 'EXPLORATOIRE', 'probability': round(probability,4), 'value': round(probability,4),
            'display': f'Environ {100*probability:.1f} % (exploratoire)',
            'interpretation': 'PSR normal approximation above selection-adjusted null threshold; not a posterior probability or forecast',
            'observed': {'sharpe_per_observation': sr,'observations': n,'skewness_moment': skew,
                         'kurtosis_Pearson_moment': kurtosis},
            'selection': parameters, 'threshold_sharpe_per_observation': threshold,
            'threshold_method': 'Expected Gaussian maximum numerical integral, including fractional effective N',
            'z_approximation': round(z,4), 'temporal_diagnostics': diagnostics,
            'assumptions_supplied': {'returns': assumption,'justification': justification,
                                    'trial_Sharpe_null_distribution': 'Gaussian, mean zero'},
            'limitations': ['Finite-sample asymptotic approximation; no scientific certification',
                           'Non-rejection does not establish IID/stationarity or finite fourth moment',
                           'Selection completeness and supplied parameters require external audit'],
            'reference': SOURCE}

def return_statistics(returns, starts, ends, available, currency, config, initial_cost_return=0.0):
    if not isinstance(config,dict) or set(config)-{'periods_per_year','interval_seconds','frequency_note',
        'risk_free','assumption','assumption_justification','selection','as_of_utc'}:
        raise ValueError('STATISTICS_CONFIGURATION_INVALID')
    x = np.asarray(returns,dtype=float)
    s,e,a = [[_utc(t) for t in v] for v in (starts,ends,available)]
    if x.ndim != 1 or not (len(x)==len(s)==len(e)==len(a)) or len(x)==0:
        raise ValueError('STATISTICS_NO_COMPLETE_RETURN_INTERVALS')
    if not np.isfinite(x).all() or (x<=-1).any() or not _number(initial_cost_return) or initial_cost_return<=-1:
        raise ValueError('STATISTICS_MISSING_NONFINITE_OR_INVALID_RETURNS_NO_FILL')
    if any(t1<=t0 or av<t1 for t0,t1,av in zip(s,e,a)) or any(s[i]!=e[i-1] for i in range(1,len(e))):
        raise ValueError('STATISTICS_INVALID_OR_NONCONTIGUOUS_INTERVALS')
    cutoff = _utc(config.get('as_of_utc',e[-1]))
    if any(av>cutoff for av in a):
        raise ValueError('STATISTICS_INFORMATION_NOT_AVAILABLE_AT_CUTOFF')
    if np.max(np.abs(x))>1e70:
        raise ValueError('STATISTICS_NUMERICAL_RANGE_EXCEEDED')
    n = len(x)
    base = {'version': VERSION,'reporting_currency': currency,'observations':n,
            'sample_start_utc':s[0].isoformat(),'sample_end_utc':e[-1].isoformat(),
            'as_of_utc':cutoff.isoformat(),'as_of_phase':30,
            'scope':'Retrospective only; no optimizer/decision feedback',
            'initial_cost_only_return':initial_cost_return,
            'initial_cost_policy':'Zero-duration initial allocation cost excluded from interval Sharpe; included in full-horizon compounded return',
            'missing_policy':'REJECT_NO_FILL','std_ddof':1,
            'return_mean_per_observation':observed(float(x.mean())),
            'volatility_per_observation':observed(float(x.std(ddof=1))) if n>=2 else unavailable('AT_LEAST_TWO_INTERVALS_REQUIRED')}
    p = config.get('periods_per_year'); seconds=config.get('interval_seconds')
    valid_frequency = (type(p) is int and 1<=p<=10_000_000 and _number(seconds) and seconds>0
                       and _text(config.get('frequency_note')))
    regular = valid_frequency and all((t1-t0).total_seconds()==seconds for t0,t1 in zip(s,e))
    reason = 'EXPLICIT_FREQUENCY_PERIODS_PER_YEAR_AND_FIXED_INTERVAL_REQUIRED' if not valid_frequency else 'IRREGULAR_INTERVALS_NO_IMPLICIT_ANNUALIZATION'
    for key in ('sharpe_per_observation','sharpe_annualized','volatility_annualized',
                'return_annualized_geometric','return_annualized_arithmetic'):
        base[key]=unavailable(reason if not regular else 'RISK_FREE_CONVENTION_MISSING')
    base['dsr']=unavailable('RISK_FREE_FREQUENCY_OR_SELECTION_PARAMETERS_MISSING')
    base['frequency']={'periods_per_year':p,'interval_seconds':seconds,'note':config.get('frequency_note'),
                       'regular_UTC_grid_verified':bool(regular),'calendar':'FIXED_UTC_INTERVALS_ONLY'}
    if not regular:
        return base
    log_growth=float(np.log1p(x).sum()+math.log1p(initial_cost_return))
    exponent=log_growth*p/n
    if abs(exponent) < 700:
        base['return_annualized_geometric']=observed(math.expm1(exponent), convention='Realized full-horizon growth ** (periods_per_year / intervals) - 1, including initial allocation cost; not a forecast')
    else:
        base['return_annualized_geometric']=unavailable('ANNUALIZED_COMPOUNDING_NUMERICAL_RANGE_EXCEEDED')
    base['return_annualized_arithmetic']=observed(float(x.mean())*p, convention='Interval-return mean * periods_per_year; initial zero-duration charge reported separately')
    rf=config.get('risk_free')
    if not isinstance(rf,dict) or set(rf)!={'annual_effective','currency','known_at_utc','provenance'}:
        return base
    if rf['currency']!=currency or not _text(rf['provenance']) or not _number(rf['annual_effective']) or rf['annual_effective']<=-1:
        base['sharpe_per_observation']=unavailable('RISK_FREE_CURRENCY_OR_CONVENTION_INVALID')
        base['sharpe_annualized']=base['sharpe_per_observation'].copy()
        base['dsr']=base['sharpe_per_observation'].copy()
        return base
    if _utc(rf['known_at_utc'])>s[0]:
        base['sharpe_per_observation']=unavailable('RISK_FREE_INFORMATION_NOT_KNOWN_AT_HORIZON_START')
        base['sharpe_annualized']=base['sharpe_per_observation'].copy();base['dsr']=base['sharpe_per_observation'].copy()
        return base
    period_rf=math.expm1(math.log1p(rf['annual_effective'])/p)
    excess=x-period_rf
    context={'currency':currency,'periods_per_year':p,'interval_seconds':seconds,
             'sample_start_utc':s[0].isoformat(),'sample_end_utc':e[-1].isoformat(),'risk_free_period':period_rf}
    context_id=hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    base.update(context_id=context_id,context=context,risk_free={'supplied':rf,'per_observation':period_rf,
        'conversion':'(1 + annual_effective) ** (1 / periods_per_year) - 1; fixed ex-ante benchmark, not actual cash accrual'})
    if n<2 or np.ptp(excess)==0 or excess.std(ddof=1)<=0:
        why='AT_LEAST_TWO_INTERVALS_REQUIRED' if n<2 else 'ZERO_EXCESS_RETURN_VARIANCE'
        base['sharpe_per_observation']=unavailable(why);base['sharpe_annualized']=unavailable(why);base['dsr']=unavailable(why)
        return base
    sr=float(excess.mean()/excess.std(ddof=1))
    base['sharpe_per_observation']=observed(sr,convention='mean(simple_return - constant_period_rf) / sample_std(excess, ddof=1)')
    diag=temporal_diagnostics(excess);base['temporal_diagnostics']=diag
    assumption=config.get('assumption'); justification=config.get('assumption_justification')
    if assumption=='IID' and _text(justification) and diag['status']=='NOT_REJECTED_NOT_PROVEN_IID':
        base['sharpe_annualized']=observed(sr*math.sqrt(p),status_detail='EXPLORATOIRE_SOUS_HYPOTHESE_IID',convention='sqrt(P) * SR, conditional on supplied IID/stationarity assumption')
        base['volatility_annualized']=observed(float(x.std(ddof=1))*math.sqrt(p),status_detail='EXPLORATOIRE_SOUS_HYPOTHESE_IID')
    else:
        base['sharpe_annualized']=unavailable('IID_ASSUMPTION_MISSING_OR_DEPENDENCE_DIAGNOSTIC_NOT_ADMISSIBLE')
        base['volatility_annualized']=base['sharpe_annualized'].copy()
    base['dsr']=deflated_sharpe(excess,config.get('selection'),context_id,assumption,justification)
    return base

def portfolio_statistics(frame, currency, config):
    """Certified engine output: first row is a cost-only anchor, never a market interval."""
    required={'timestamp_utc','portfolio_return','equity','portfolio_id','valuation_event_phase'}
    if not required<=set(frame) or frame.empty or frame.portfolio_id.nunique()!=1:
        raise ValueError('STATISTICS_SINGLE_PORTFOLIO_REQUIRED')
    if not isinstance(config,dict): raise ValueError('STATISTICS_CONFIGURATION_INVALID')
    frame=frame.sort_values('timestamp_utc').copy()
    ts=[_utc(t) for t in frame.timestamp_utc]
    if len(set(ts))!=len(ts):
        raise ValueError('STATISTICS_DUPLICATE_TIMESTAMPS')
    cutoff=_utc(config.get('as_of_utc',ts[-1]))
    frame=frame.loc[[t<=cutoff for t in ts]].copy();ts=[_utc(t) for t in frame.timestamp_utc]
    if len(frame)<2:
        return {'version':VERSION,'dsr':unavailable('NO_COMPLETE_POST_ALLOCATION_INTERVAL'),
                'sharpe_per_observation':unavailable('NO_COMPLETE_POST_ALLOCATION_INTERVAL')}
    x=frame.portfolio_return.to_numpy(dtype=float)
    if not np.allclose(np.cumprod(1+x),frame.equity.to_numpy(),rtol=1e-12,atol=1e-12):
        raise ValueError('STATISTICS_NAV_RETURN_INCONSISTENCY')
    if x[0]>1e-12 or frame.valuation_event_phase.iloc[0]!=30:
        raise ValueError('STATISTICS_INITIAL_ALLOCATION_ANCHOR_REQUIRED')
    options=dict(config,as_of_utc=cutoff.isoformat())
    return portfolio_statistics_result(return_statistics(x[1:],ts[:-1],ts[1:],ts[1:],currency,options,float(x[0])),frame)

def portfolio_statistics_result(result,frame):
    result['portfolio_id']=str(frame.portfolio_id.iloc[0])
    result['underlying_exposure']=unavailable('Strategy weights are insufficient: time-stamped instrument positions, contract multipliers, currency conversions and NAV required')
    return result

"""Thin, version-pinned Qlib objective/estimator adapter; no alternate engine."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from .event_clock import require
from .portfolio_capacity import validate_capacity
from .experiment_store import read_json
QUANT_METHODS=('MINIMUM_VARIANCE','MEAN_VARIANCE','RISK_PARITY')
COVARIANCE_ESTIMATORS=('EMPIRICAL','SHRINK_LW','SHRINK_FIXED')

def capabilities():
    return read_json(Path(__file__).resolve().parents[1]/'QLIB_INTEGRATION_V1.json')

def verify_qlib_api():
    import qlib
    metadata=capabilities()
    require(qlib.__version__==metadata['qlib_version'],'QLIB_VERSION_REQUIRES_REQUALIFICATION')
    root=Path(qlib.__file__).resolve().parent
    for name,expected in metadata['source_sha256'].items():
        p=root/name
        with p.open('rb') as f:observed=hashlib.file_digest(f,'sha256').hexdigest()
        require(observed==expected,'QLIB_API_SOURCE_DRIFT:'+name)
    return metadata['qlib_version']

def validate_quant_options(config):
    require(config.covariance_estimator in COVARIANCE_ESTIMATORS,'UNSUPPORTED_COVARIANCE_ESTIMATOR')
    require(type(config.shrinkage_alpha) in (int,float) and np.isfinite(config.shrinkage_alpha)
            and 0<=config.shrinkage_alpha<=1,'INVALID_SHRINKAGE_ALPHA')
    require(type(config.risk_aversion) in (int,float) and np.isfinite(config.risk_aversion) and config.risk_aversion>0,
            'POSITIVE_RISK_AVERSION_REQUIRED')
    if config.method not in QUANT_METHODS:
        require(config.covariance_estimator=='EMPIRICAL','COVARIANCE_OPTION_ONLY_FOR_QUANT_METHOD')
    if config.method!='MEAN_VARIANCE':
        require(config.risk_aversion==1.0,'RISK_AVERSION_ONLY_FOR_MEAN_VARIANCE')
    if config.risk_periods_per_year is None:
        require(config.risk_frequency_note is None,'RISK_FREQUENCY_REQUIRES_EXPLICIT_PERIODS_PER_YEAR')
    else:
        require(type(config.risk_periods_per_year) is int and config.risk_periods_per_year>0,
                'POSITIVE_INTEGER_PERIODS_PER_YEAR_REQUIRED')
        require(isinstance(config.risk_frequency_note,str) and 0<len(config.risk_frequency_note.strip())<=1000,
                'EXPLICIT_RISK_FREQUENCY_JUSTIFICATION_REQUIRED')

def estimate_covariance(values,estimator='EMPIRICAL',alpha=.1):
    X=np.asarray(values,dtype=np.float64)
    require(X.ndim==2 and X.shape[0]>=2 and X.shape[1]>=1 and np.isfinite(X).all(),'FINITE_PAST_RETURN_MATRIX_REQUIRED')
    validate_capacity(int(X.size),int(X.shape[1]))
    require(estimator in COVARIANCE_ESTIMATORS,'UNSUPPORTED_COVARIANCE_ESTIMATOR')
    empirical=np.atleast_2d(np.cov(X,rowvar=False,ddof=1))
    target=np.eye(X.shape[1])*np.trace(empirical)/X.shape[1]
    identity_target=(X.shape[1]==1 or np.array_equal(empirical,target))
    if estimator=='EMPIRICAL' or identity_target:
        if estimator!='EMPIRICAL':verify_qlib_api()
        covariance=empirical.copy()
    else:
        verify_qlib_api()
        from qlib.model.riskmodel import ShrinkCovEstimator
        selected={'SHRINK_LW':'lw','SHRINK_OAS':'oas','SHRINK_FIXED':float(alpha)}[estimator]
        require(type(alpha) in (int,float) and np.isfinite(alpha) and 0<=alpha<=1,'INVALID_SHRINKAGE_ALPHA')
        model=ShrinkCovEstimator(alpha=selected,target='const_var',nan_option='ignore',
                                 assume_centered=False,scale_return=False)
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning)
            try:covariance=np.atleast_2d(np.asarray(model.predict(X.copy(),is_price=False),dtype=float))*len(X)/(len(X)-1)
            except (RuntimeWarning,FloatingPointError) as error:
                raise ValueError('QLIB_COVARIANCE_NUMERICAL_FAILURE') from error
    require(covariance.shape==(X.shape[1],X.shape[1]) and np.isfinite(covariance).all(),'COVARIANCE_SHAPE_OR_FINITE_INVALID')
    require(np.allclose(covariance,covariance.T,rtol=1e-12,atol=1e-15),'COVARIANCE_NOT_SYMMETRIC')
    covariance=(covariance+covariance.T)/2
    scale=float(np.max(np.abs(covariance)))
    eigenvalues=np.linalg.eigvalsh(covariance)
    require(float(eigenvalues.min())>=-max(1e-15,scale*1e-10),'COVARIANCE_NOT_POSITIVE_SEMIDEFINITE')
    return covariance,{'estimator':estimator,'target':'const_var' if estimator!='EMPIRICAL' else None,
      'alpha':float(alpha) if estimator=='SHRINK_FIXED' else 'lw' if estimator=='SHRINK_LW' else 'oas' if estimator=='SHRINK_OAS' else None,
      'covariance_scale':'sample ddof1; Qlib ddof0 multiplied by T/(T-1)',
      'degeneracy_policy':'Target equals empirical covariance; analytical identity, no alpha inferred' if identity_target and estimator!='EMPIRICAL' else None,
      'observations':len(X),'minimum_eigenvalue':float(eigenvalues.min()),
      'empirical_covariance_ddof1':empirical.tolist(),'difference_from_empirical_frobenius':float(np.linalg.norm(covariance-empirical))}

@lru_cache(maxsize=1)
def _optimizer_class():
    verify_qlib_api()
    from qlib.contrib.strategy.optimizer import PortfolioOptimizer
    import scipy.optimize as so
    class CheckedQlibOptimizer(PortfolioOptimizer):
        """Two installed-Qlib hooks: constraints and checked solver, objectives unchanged."""
        def __init__(self,method,lamb,lower,upper,matrix,gradient=None):
            super().__init__(method=method,lamb=lamb,scale_return=False,tol=1e-12)
            self.lower=lower;self.upper=upper;self.receipt={};self.matrix=matrix;self.gradient=gradient
        def _get_constrains(self,w0=None):
            require(w0 is None,'QUANT_TURNOVER_CONSTRAINT_NOT_SUPPORTED')
            return so.Bounds(self.lower,self.upper),[{'type':'eq','fun':lambda w:w.sum()-1,'jac':lambda w:np.ones_like(w)}]
        def _solve(self,n,obj,bounds,cons):
            x0=np.full(n,1/n)
            if self.method=='rp':
                candidate=self._optimize_inv(self.matrix)
                warm_start='INVERSE_VOLATILITY_POSITIVE_MARGINALS'
                if ((candidate>=self.lower).all() and (candidate<=self.upper).all()
                    and (self.matrix@candidate>0).all()):
                    x0=candidate
                else:
                    # Phase-I linear feasibility only; allocation still solves Qlib's RP objective.
                    # Find an interior point with positive weights AND positive marginal variances.
                    domain=so.linprog(np.r_[np.zeros(n),-1.],
                        A_ub=np.vstack([np.c_[-np.eye(n),np.ones(n)],
                                        np.c_[-self.matrix,np.ones(n)]]),
                        b_ub=np.zeros(2*n),A_eq=np.r_[np.ones(n),0.][None,:],b_eq=[1.],
                        bounds=[(self.lower,self.upper)]*n+[(0.,None)],method='highs')
                    require(domain.success and np.isfinite(domain.x).all()
                            and domain.x[-1]>1e-10,'RISK_PARITY_POSITIVE_MARGINAL_DOMAIN_INFEASIBLE')
                    x0=domain.x[:-1]
                    require((self.matrix@x0>0).all(),'RISK_PARITY_INITIAL_MARGINALS_NOT_POSITIVE')
                    warm_start='LINEAR_POSITIVE_MARGINAL_DOMAIN_FEASIBILITY'
            result=so.minimize(obj,x0,jac=self.gradient,method='SLSQP',bounds=bounds,constraints=cons,
                               options={'ftol':1e-13,'maxiter':1000})
            require(bool(result.success),'QLIB_OPTIMIZATION_FAILED:'+str(result.message))
            w=np.asarray(result.x,dtype=float)
            require(w.shape==(n,) and np.isfinite(w).all() and abs(w.sum()-1)<=1e-12
                    and (w>=self.lower-1e-12).all() and (w<=self.upper+1e-12).all(),
                    'QLIB_OPTIMIZER_INFEASIBLE_OUTPUT')
            self.receipt={'warm_start':warm_start if self.method=='rp' else 'EQUAL_WEIGHT', 'success':True,'status':int(getattr(result,'status',0)),'message':str(result.message),
                          'iterations':int(getattr(result,'nit',0)),'objective_scaled':float(result.fun)}
            return w
    return CheckedQlibOptimizer

def _kkt_residual(gradient,x,lower,upper):
    if upper-lower<=1e-12:return 0.0
    free=(x>lower+1e-7)&(x<upper-1e-7)
    if free.any():level=float(np.median(gradient[free]))
    else:
        lows=gradient[x<=lower+1e-7];highs=gradient[x>=upper-1e-7]
        min_level=float(np.max(highs)) if len(highs) else -np.inf
        max_level=float(np.min(lows)) if len(lows) else np.inf
        if min_level>max_level:return min_level-max_level
        level=min(max(0.0,min_level),max_level)
    residual=np.zeros(len(x))
    residual[free]=np.abs(gradient[free]-level)
    atlower=x<=lower+1e-7;atupper=x>=upper-1e-7
    residual[atlower]=np.maximum(0,level-gradient[atlower])
    residual[atupper]=np.maximum(residual[atupper],np.maximum(0,gradient[atupper]-level))
    return float(np.max(residual))

def optimize_covariance(covariance,method,*,expected_returns=None,cash_weight=.1,min_weight=0.,
                        max_weight=.8,max_positions=None,risk_aversion=1.):
    require(method in QUANT_METHODS,'UNSUPPORTED_QUANT_METHOD')
    S=np.asarray(covariance,dtype=float)
    require(S.ndim==2 and len(S)>0 and S.shape==(len(S),len(S)) and np.isfinite(S).all(),'INVALID_COVARIANCE')
    n=len(S);validate_capacity(0,n)
    require(np.allclose(S,S.T,rtol=1e-12,atol=1e-15),'COVARIANCE_NOT_SYMMETRIC')
    require(type(cash_weight) in (int,float) and np.isfinite(cash_weight) and 0<=cash_weight<=1,
            'INVALID_QUANT_CASH_WEIGHT')
    budget=1-cash_weight
    if budget==0:return np.zeros(n),{'status':'ALL_CASH_NO_RISK_ALLOCATION','solver_used':False}
    require(max_positions is None or n<=max_positions,'QUANT_SUBSET_CARDINALITY_OPTIMIZER_NOT_SUPPORTED')
    require(np.isfinite([min_weight,max_weight]).all() and 0<=min_weight<=max_weight<=1,'INVALID_QUANT_WEIGHT_BOUNDS')
    lower,upper=min_weight/budget,min(max_weight/budget,1.0)
    require(n*lower<=1+1e-12 and n*upper>=1-1e-12,'QUANT_WEIGHT_CONSTRAINTS_INFEASIBLE')
    variance_scale=float(np.mean(np.diag(S)))
    require(variance_scale>0 and np.isfinite(variance_scale),'NONPOSITIVE_COVARIANCE_SCALE')
    eigenvalues=np.linalg.eigvalsh(S)
    require(eigenvalues.min()>=-variance_scale*1e-10,'COVARIANCE_NOT_POSITIVE_SEMIDEFINITE')
    if method=='RISK_PARITY':
        require(eigenvalues.min()>variance_scale*1e-10,'RISK_PARITY_REQUIRES_POSITIVE_DEFINITE_COVARIANCE_USE_EXPLICIT_SHRINKAGE')
    if method=='RISK_PARITY':
        # Qlib's RP objective divides by marginal variance; zero weights are
        # outside equal-positive-risk allocation. Expose this numerical domain.
        lower=max(lower,1e-12)
        require(n*lower<=1+1e-12,'RISK_PARITY_POSITIVE_DOMAIN_INFEASIBLE')
    objective_scale=variance_scale
    scaled=S/objective_scale
    mu=None
    if method=='MEAN_VARIANCE':
        require(expected_returns is not None,'EXPECTED_RETURNS_REQUIRED')
        mu=np.asarray(expected_returns,dtype=float)
        require(mu.shape==(n,) and np.isfinite(mu).all(),'INVALID_EXPECTED_RETURNS')
        require(type(risk_aversion) in (int,float) and np.isfinite(risk_aversion) and risk_aversion>0,'POSITIVE_RISK_AVERSION_REQUIRED')
        # Scale BOTH terms together. Daily means / daily variances can be
        # hundreds apart; a variance-only scale makes the QP needlessly large.
        objective_scale=max(variance_scale,float(np.max(np.abs(mu))),risk_aversion*budget*variance_scale)
        scaled=S/objective_scale
        mu_scaled=mu/objective_scale
    else:
        require(expected_returns is None,'EXPECTED_RETURNS_ONLY_FOR_MEAN_VARIANCE')
        mu_scaled=None
    gradient=(lambda x:2*scaled@x) if method=='MINIMUM_VARIANCE' else (
             (lambda x:2*risk_aversion*budget*scaled@x-mu_scaled) if method=='MEAN_VARIANCE' else None)
    optimizer=_optimizer_class()({'MINIMUM_VARIANCE':'gmv','MEAN_VARIANCE':'mvo','RISK_PARITY':'rp'}[method],
                                risk_aversion*budget if method=='MEAN_VARIANCE' else 1.0,lower,upper,scaled,gradient)
    with warnings.catch_warnings():
        warnings.simplefilter('error',RuntimeWarning)
        try:x=optimizer(scaled,r=mu_scaled)
        except (RuntimeWarning,FloatingPointError) as error:
            raise ValueError('QLIB_OPTIMIZATION_NUMERICAL_FAILURE') from error
    w=np.asarray(x)*budget
    variance=float(w@S@w)
    require(np.isfinite(variance) and variance>0,'OPTIMIZED_VARIANCE_NOT_POSITIVE')
    contributions=w*(S@w)
    rc_error=float(np.max(np.abs(contributions/variance-1/n)))
    kkt=None
    if method=='RISK_PARITY':
        require(rc_error<=5e-5,'RISK_PARITY_EQUAL_CONTRIBUTIONS_NOT_ACHIEVED_WITH_CONSTRAINTS')
    else:
        gradient=2*scaled@x if method=='MINIMUM_VARIANCE' else 2*risk_aversion*budget*scaled@x-mu_scaled
        kkt=_kkt_residual(gradient,x,lower,upper)
        require(kkt<=1e-5*max(1.,float(np.max(np.abs(gradient)))),'OPTIMIZER_STATIONARITY_CHECK_FAILED')
    return w,{'method':method,'qlib_version':verify_qlib_api(),'solver':'SciPy SLSQP using pinned Qlib objectives',
      'solver_receipt':optimizer.receipt,'cash_weight':cash_weight,'weight_bounds_full_NAV':[min_weight,max_weight],
      'variance_per_observation':variance,'component_variance_contributions':contributions.tolist(),
      'risk_parity_max_fraction_error':rc_error if method=='RISK_PARITY' else None,'kkt_residual_scaled':kkt,
      'concentration_HHI':float(w@w),'max_weight_observed':float(w.max()),
      'expected_return_per_observation':None if mu is None else float(w@mu),
      'objective_definition':'variance' if method=='MINIMUM_VARIANCE' else '-w@past_mean + risk_aversion*w@cov@w' if method=='MEAN_VARIANCE' else 'equal component variance contribution',
      'conditioning':'Covariance and expected returns divided by the same positive objective scale; no expected-return volatility matching',
      'objective_scale':objective_scale,
      'risk_parity_normalized_positive_floor':1e-12 if method=='RISK_PARITY' else None,
      'future_performance_guaranteed':False}

def quantitative_weights(values,config):
    if config.cash_weight==1:
        return np.zeros(np.asarray(values).shape[1]),{'status':'ALL_CASH_NO_RISK_ALLOCATION','solver_used':False,
                 'covariance_estimation':{'status':'NOT_USED_ALL_CASH'},'expected_return_assumption':'NOT_USED'}
    covariance,estimate=estimate_covariance(values,config.covariance_estimator,config.shrinkage_alpha)
    expected=np.mean(values,axis=0) if config.method=='MEAN_VARIANCE' else None
    w,diagnostic=optimize_covariance(covariance,config.method,expected_returns=expected,cash_weight=config.cash_weight,
           min_weight=config.min_weight,max_weight=config.max_weight,max_positions=config.max_positions,
           risk_aversion=config.risk_aversion)
    diagnostic.update(covariance_estimation=estimate,covariance_used=covariance.tolist(),
                      expected_return_assumption='Past arithmetic sample mean over exactly the admitted window; noisy estimate, no future guarantee' if expected is not None else 'NOT_USED')
    return w,diagnostic

def qlib_risk_analysis(returns,periods_per_year,frequency_note):
    require(type(periods_per_year) is int and periods_per_year>0,'EXPLICIT_PERIODS_PER_YEAR_REQUIRED')
    require(isinstance(frequency_note,str) and bool(frequency_note.strip()),'EXPLICIT_RISK_FREQUENCY_JUSTIFICATION_REQUIRED')
    r=pd.Series(returns,dtype=float).reset_index(drop=True)
    require(len(r)>=2 and np.isfinite(r).all() and (r>-1).all(),'INVALID_RISK_ANALYSIS_RETURNS')
    verify_qlib_api()
    from qlib.contrib.evaluate import risk_analysis
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        table=risk_analysis(r,N=periods_per_year,freq=None,mode='sum')['risk']
    std=float(r.std(ddof=1))
    ratio=float(table['information_ratio']) if std>0 else None
    require(std>=0 and all(np.isfinite(float(table[k])) for k in ('mean','std','annualized_return','max_drawdown'))
            and (ratio is None or np.isfinite(ratio)),'QLIB_RISK_ANALYSIS_NONFINITE')
    return {'qlib_version':verify_qlib_api(),'mode':'sum','periods_per_year_declared':periods_per_year,
      'frequency_justification':frequency_note,'mean_per_observation':float(table['mean']),
      'std_per_observation_ddof1':float(table['std']),'linear_annualized_return_not_CAGR':float(table['annualized_return']),
      'zero_reference_information_ratio_not_Sharpe':ratio,
      'undefined_ratio_reason':'ZERO_SAMPLE_VOLATILITY' if ratio is None else None,
      'arithmetic_path_drawdown_excluding_initial_anchor':float(table['max_drawdown']),
      'NAV_drawdown':'Use existing PRISM max_drawdown, which includes initial NAV',
      'scope':'Retrospective realized portfolio increments; never used as allocation inputs'}

from dataclasses import replace
import json
from pathlib import Path
import socket
import tempfile
import unittest

import numpy as np
import pandas as pd
from examples.synthetic_portfolio import ASSETS, STRATEGIES, return_fixture
from aurum_qlib_lab.event_clock import CausalContractError, event_key
from aurum_qlib_lab.strategy_series import stamp_payload_hashes, validate_return_series
from aurum_qlib_lab.portfolio_lab import PortfolioConfig, weights_at, simulate_certification, run_portfolio
from aurum_qlib_lab.quantitative import estimate_covariance, optimize_covariance, verify_qlib_api
from public_prism.demo import run_demo, render_html


class PublicPortfolioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.paths, cls.report = run_demo()

    def test_six_methods_have_real_qlib_receipts(self):
        self.assertEqual(len(self.report['results']), 6)
        calls=self.report['qlib_calls']
        for name in ['_optimize_gmv','_optimize_mvo','_optimize_rp']:
            self.assertGreater(calls['contrib/strategy/optimizer/optimizer.py:'+name],0)
        self.assertGreater(calls['model/riskmodel/base.py:predict'],0)
        self.assertEqual(calls['contrib/evaluate.py:risk_analysis'],6)
        self.assertFalse(self.report['scientific_validation_real_portfolio'])

    def test_source_qlib_hashes_match_installed_distribution(self):
        self.assertEqual(verify_qlib_api(),'0.9.7')

    def test_synthetic_inputs_are_reproducible(self):
        pd.testing.assert_frame_equal(self.frame,return_fixture())
        self.assertTrue(set(self.frame.asset)==set(ASSETS))
        self.assertTrue(all(x.startswith('DEMO_') for x in ASSETS))

    def test_weights_cash_and_risk_constraints(self):
        for method,result in self.report['results'].items():
            with self.subTest(method=method):
                for allocation in result['allocation_history']:
                    w=np.asarray(list(allocation['weights'].values()))
                    self.assertAlmostEqual(w.sum()+allocation['cash_weight'],1,places=12)
                    self.assertTrue((w>=0).all() and (w<=.8+1e-12).all())
                if method in ('MINIMUM_VARIANCE','MEAN_VARIANCE'):
                    self.assertLess(result['latest_allocation']['quantitative']['kkt_residual_scaled'],1e-5)
                if method=='RISK_PARITY':
                    self.assertLessEqual(result['latest_allocation']['quantitative']['risk_parity_max_fraction_error'],5e-5)

    def configs(self):
        return [PortfolioConfig('MANUAL',manual_weights=dict(zip(STRATEGIES,[.4,.2,.3]))),
                PortfolioConfig('EQUAL_WEIGHT'),PortfolioConfig('INVERSE_VOLATILITY'),
                *[PortfolioConfig(x,covariance_estimator='SHRINK_LW')
                  for x in ('MINIMUM_VARIANCE','MEAN_VARIANCE','RISK_PARITY')]]

    def test_future_mutation_does_not_change_allocation(self):
        time=self.frame.timestamp_utc.unique()[119]
        changed=self.frame.copy()
        future=changed.timestamp_utc>time
        changed.loc[future,'return']=.3+np.arange(int(future.sum()))*.0003
        changed=stamp_payload_hashes(changed)
        for config in self.configs():
            with self.subTest(method=config.method):
                a,ra=weights_at(self.frame,config,time,ASSETS)
                b,rb=weights_at(changed,config,time,ASSETS)
                np.testing.assert_array_equal(a,b)
                self.assertEqual(ra,rb)

    def test_truncated_history_has_same_allocation(self):
        time=self.frame.timestamp_utc.unique()[119]
        truncated=stamp_payload_hashes(self.frame.loc[self.frame.timestamp_utc<=time].copy())
        for config in self.configs():
            with self.subTest(method=config.method):
                a,ra=weights_at(self.frame,config,time,ASSETS)
                b,rb=weights_at(truncated,config,time,ASSETS)
                np.testing.assert_array_equal(a,b)
                self.assertEqual(ra,rb)

    def test_event_order_and_next_interval_application(self):
        cfg=PortfolioConfig('EQUAL_WEIGHT',cost_rate=0)
        path,decisions,_=simulate_certification(self.frame,cfg,ASSETS,'clock')
        first=decisions[0]
        events=[event_key(pd.Timestamp(first[k]['timestamp_utc']),int(first[k]['event_phase']))
                for k in ('information_cutoff_event','rebalance_decision_event','execution_event')]
        self.assertTrue(events[0]<events[1]<events[2])
        matrix=validate_return_series(self.frame,ASSETS)
        w=np.asarray([first['weights'][x] for x in matrix.columns])
        self.assertAlmostEqual(path.equity.iloc[1],1+float(w@matrix.iloc[cfg.historical_window]),places=12)

    def test_accounting_costs_and_drift_hand_calculation(self):
        frame=return_fixture(6)
        frame['return']=[.01 if x==STRATEGIES[0] else -.02 if x==STRATEGIES[1] else .03 for x in frame.strategy_id]
        frame=stamp_payload_hashes(frame)
        cfg=PortfolioConfig('MANUAL',historical_window=2,rebalance_every_observations=100,
            manual_weights=dict(zip(STRATEGIES,[.4,.2,.3])),cost_rate=.01)
        path,decisions,metrics=simulate_certification(frame,cfg,ASSETS,'hand-calculated')
        expected=(1-.009)*(.1+.4*1.01**4+.2*.98**4+.3*1.03**4)
        self.assertEqual(len(decisions),1)
        self.assertAlmostEqual(metrics['final_equity'],expected,places=12)
        self.assertAlmostEqual(metrics['costs_total_initial_nav_units'],.009,places=12)
        self.assertAlmostEqual(metrics['max_drawdown'],-.009,places=12)

    def test_malformed_series_fail_closed(self):
        for attack in ['missing','nan','unsorted','duplicate','naive','asset','currency','cost','hash']:
            with self.subTest(attack=attack):
                bad=self.frame.copy()
                if attack=='missing':bad=stamp_payload_hashes(bad.drop(index=len(bad)-1))
                elif attack=='nan':bad.loc[101,'return']=np.nan
                elif attack=='unsorted':bad=bad.iloc[::-1]
                elif attack=='duplicate':bad=pd.concat([bad,bad.iloc[[0]]])
                elif attack=='naive':bad['timestamp_utc']=bad.timestamp_utc.dt.tz_localize(None)
                elif attack=='asset':bad.loc[101,'asset']='UNADMITTED'
                elif attack=='currency':bad.loc[101,'reporting_currency']='OTHER'
                elif attack=='cost':bad.loc[101,'cost_status']='UNKNOWN'
                elif attack=='hash':bad.loc[101,'source_hash']='0'*64
                with self.assertRaises((ValueError,CausalContractError)):
                    validate_return_series(bad,ASSETS)

    def test_late_publication_prevents_rebalance(self):
        time=self.frame.timestamp_utc.unique()[47]
        bad=self.frame.copy()
        bad.loc[bad.timestamp_utc.eq(time),'available_at_utc']=time+pd.Timedelta(hours=4)
        with self.assertRaisesRegex(CausalContractError,'NOT_YET_AVAILABLE'):
            weights_at(stamp_payload_hashes(bad),PortfolioConfig('EQUAL_WEIGHT'),time,ASSETS)

    def test_infeasible_constraints_are_not_replaced(self):
        cfg=PortfolioConfig('MANUAL',manual_weights=dict(zip(STRATEGIES,[.4,.2,.3])))
        for changed in [replace(cfg,cash_weight=.2),replace(cfg,max_weight=.3),replace(cfg,min_weight=.3),
                        replace(cfg,max_positions=2),replace(cfg,historical_window=1),
                        replace(cfg,rebalance_every_observations=0),replace(cfg,cost_rate=-.1)]:
            with self.subTest(config=changed):
                with self.assertRaises(CausalContractError):
                    weights_at(self.frame,changed,self.frame.timestamp_utc.unique()[47],ASSETS)

    def test_minimum_variance_known_diagonal_solution(self):
        covariance=np.diag([1.,4.,9.])*.0001
        weights,receipt=optimize_covariance(covariance,'MINIMUM_VARIANCE',cash_weight=.1,max_weight=1.)
        expected=.9*(1/np.diag(covariance))/(1/np.diag(covariance)).sum()
        np.testing.assert_allclose(weights,expected,rtol=1e-6,atol=1e-8)
        self.assertTrue(receipt['solver_receipt']['success'])

    def test_risk_parity_known_diagonal_solution(self):
        covariance=np.diag([1.,4.,9.])*.0001
        weights,receipt=optimize_covariance(covariance,'RISK_PARITY',cash_weight=.1,max_weight=1.)
        inv=1/np.sqrt(np.diag(covariance))
        np.testing.assert_allclose(weights,.9*inv/inv.sum(),rtol=1e-5,atol=1e-7)

    def test_unsupported_oas_estimator_stays_disabled(self):
        matrix=validate_return_series(self.frame,ASSETS).iloc[:48].to_numpy()
        with self.assertRaisesRegex(CausalContractError,'UNSUPPORTED_COVARIANCE_ESTIMATOR'):
            estimate_covariance(matrix,'SHRINK_OAS')

    def test_sharpe_dsr_and_real_validation_are_not_invented(self):
        for result in self.report['results'].values():
            self.assertEqual(result['statistics']['sharpe_per_observation']['status'],'NON_CALCULABLE')
            self.assertEqual(result['statistics']['dsr']['status'],'NON_CALCULABLE')
            self.assertIn('not_Sharpe',str(result['metrics']['qlib_risk_analysis']))

    def test_no_production_certificate_is_fabricated(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises((FileNotFoundError,ValueError)):
                run_portfolio(folder,self.frame,PortfolioConfig('EQUAL_WEIGHT'),ASSETS,'not-certified')

    def test_json_contains_no_nonfinite_values(self):
        json.dumps(self.report,allow_nan=False)

    def test_html_explains_fiction_and_actual_qlib_calls(self):
        page=render_html(self.report)
        self.assertIn('synthétiques',page)
        self.assertIn('_optimize_gmv',page)
        self.assertIn('scientifique',page)

    def test_external_network_is_refused(self):
        with self.assertRaisesRegex(PermissionError,'EXTERNAL_NETWORK_REFUSED'):
            socket.getaddrinfo('example.invalid',443)

    def test_arl_is_not_imported(self):
        self.assertFalse(any(x.startswith(('aurum_bt','arl_backend','AURUM_RESEARCH_LAB')) for x in __import__('sys').modules))

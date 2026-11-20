"""A reproducible synthetic portfolio through the existing PRISM/Qlib adapter."""
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import html
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from examples.synthetic_portfolio import return_fixture, ASSETS, STRATEGIES, SEED
from aurum_qlib_lab.portfolio_lab import PortfolioConfig, simulate_certification
from aurum_qlib_lab.quantitative import verify_qlib_api
from aurum_qlib_lab.statistics import portfolio_statistics


@contextmanager
def qlib_call_trace():
    """Observe genuine Python frame entries inside installed Qlib, without patching it."""
    import qlib
    root = Path(qlib.__file__).resolve().parent
    files = {'contrib/strategy/optimizer/optimizer.py': {'__call__','_optimize_gmv','_optimize_mvo','_optimize_rp'},
             'model/riskmodel/base.py': {'predict'}, 'model/riskmodel/shrink.py': {'_predict'},
             'contrib/evaluate.py': {'risk_analysis'}}
    lookup = {str((root / file).resolve()).casefold(): (file, names) for file,names in files.items()}
    calls = Counter()
    previous = sys.getprofile()
    def observe(frame, event, arg):
        if event == 'call':
            item = lookup.get(frame.f_code.co_filename.casefold())
            if item and frame.f_code.co_name in item[1]:
                calls[item[0] + ':' + frame.f_code.co_name] += 1
    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


def run_demo(observations=240):
    if type(observations) is not int or not 96 <= observations <= 2000:
        raise ValueError('SYNTHETIC_DEMO_OBSERVATIONS_MUST_BE_96_TO_2000')
    version = verify_qlib_api()
    frame = return_fixture(observations)
    # Explicit fiction-only frequency: continuous 4h calendar, 365 days/year.
    # It is not an exchange calendar or a calibration to any real instrument.
    frequency = 'Fiction : grille continue de 4 heures, 6 observations/jour et 365 jours/an, sans jours de marché réels.'
    base = PortfolioConfig('EQUAL_WEIGHT', historical_window=48, rebalance_every_observations=24,
                           cash_weight=.1, max_weight=.8, max_positions=3, cost_rate=.001,
                           risk_periods_per_year=365*6, risk_frequency_note=frequency)
    configurations = [replace(base, method='MANUAL', manual_weights=dict(zip(STRATEGIES,[.4,.2,.3]))),
                      base, replace(base,method='INVERSE_VOLATILITY'),
                      *[replace(base,method=name,covariance_estimator='SHRINK_LW')
                        for name in ['MINIMUM_VARIANCE','MEAN_VARIANCE','RISK_PARITY']]]
    results = {}
    outputs = {}
    with qlib_call_trace() as calls:
        for config in configurations:
            path, decisions, metrics = simulate_certification(frame,config,ASSETS,'PUBLIC_'+config.method)
            stats = portfolio_statistics(path,'SYNTHETIC_COMMON_NAV_UNITS',
                {'periods_per_year':365*6,'interval_seconds':14400,'frequency_note':frequency,
                 'risk_free':None,'as_of_utc':path.timestamp_utc.iloc[-1].isoformat()})
            results[config.method] = {'latest_allocation': decisions[-1], 'metrics': metrics,
                                     'statistics': stats, 'allocation_history': decisions}
            outputs[config.method] = path
    required = ['contrib/strategy/optimizer/optimizer.py:_optimize_gmv',
                'contrib/strategy/optimizer/optimizer.py:_optimize_mvo',
                'contrib/strategy/optimizer/optimizer.py:_optimize_rp',
                'model/riskmodel/base.py:predict','contrib/evaluate.py:risk_analysis']
    if not all(calls[name] > 0 for name in required):
        raise RuntimeError('REAL_QLIB_CALL_TRACE_INCOMPLETE')
    input_identity = hashlib.sha256(np.asarray(frame['return'],dtype='<f8').tobytes()).hexdigest()
    report = {'scope':'PUBLIC_SYNTHETIC_SMOKE_ONLY', 'scientific_validation_real_portfolio':False,
              'arl_required':False,'seed':SEED,'observations_per_series':observations,
              'assets':list(ASSETS),'strategies':list(STRATEGIES),'qlib_version':version,
              'input_returns_sha256':input_identity,'qlib_calls':dict(sorted(calls.items())),
              'results':results, 'unavailable':{
                  'real_portfolio_scientific_validation':'NOT_PERFORMED',
                  'sharpe':'NON_CALCULABLE: aucune convention de taux sans risque fournie',
                  'deflated_sharpe':'NON_CALCULABLE: aucun historique complet de sélection ni hypothèse IID justifiée',
                  'underlying_exposure':'NON_CALCULABLE: rendements de composantes sans positions ni multiplicateurs',
                  'real_market_performance':'NOT_TESTED'}}
    return frame, outputs, report


def render_html(report):
    escape = html.escape
    def pct(value): return f'{value:.2%}'
    rows = []
    risk_rows = []
    for method,result in report['results'].items():
        allocation=result['latest_allocation']; metrics=result['metrics']
        weights=' · '.join(escape(k.replace('FIXTURE_',''))+': '+pct(v) for k,v in allocation['weights'].items())
        risk=metrics['qlib_risk_analysis']
        ratio=risk['zero_reference_information_ratio_not_Sharpe']
        risk_rows.append('<tr><th>'+escape(method)+'</th><td>'+pct(risk['mean_per_observation'])+
            '</td><td>'+pct(risk['std_per_observation_ddof1'])+'</td><td>'+pct(risk['linear_annualized_return_not_CAGR'])+
            '</td><td>'+('Non défini' if ratio is None else f'{ratio:.3f}')+'</td><td>'+
            pct(risk['arithmetic_path_drawdown_excluding_initial_anchor'])+'</td></tr>')
        rows.append('<tr><th>'+escape(method)+'</th><td>'+weights+'</td><td>'+pct(allocation['cash_weight'])+
            '</td><td>'+pct(metrics['cumulative_return'])+'</td><td>'+pct(metrics['max_drawdown'])+
            '</td><td>'+pct(metrics['volatility_per_observation'])+'</td><td>'+f"{metrics['turnover_risky_l1_total']:.3f}"+
            '</td><td>'+pct(metrics['costs_total_initial_nav_units'])+'</td></tr>')
    trace='\n'.join(f'{name}: {count}' for name,count in report['qlib_calls'].items())
    unavailable=''.join('<li>'+escape(k)+': '+escape(v)+'</li>' for k,v in report['unavailable'].items())
    return ('''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PRISM · Portefeuille fictif</title><style>
*{box-sizing:border-box}body{margin:0;color:#182f38;background:#f3f2ed;font:16px/1.6 system-ui,sans-serif}
header,main,footer{max-width:1480px;margin:auto;padding:28px}header{border-bottom:1px solid #c7cccb}
.brand{font:52px Georgia,serif;margin:0}.eyebrow{font-size:12px;letter-spacing:.16em;color:#796330;text-transform:uppercase}
h1{font:36px Georgia,serif}h2{font:25px Georgia,serif}.notice,section{background:white;border:1px solid #d6dcd8;border-radius:8px;padding:22px;margin:20px 0}.notice{border-left:5px solid #a68b45}
.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:14px 10px;border-bottom:1px solid #e2e6e2;vertical-align:top}thead{background:#eaf0ec}td{font-variant-numeric:tabular-nums}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}
footer{font-size:13px;color:#53676c}@media(max-width:760px){header,main,footer{padding:18px}h1{font-size:30px}.brand{font-size:42px}}</style>
<header><p class="eyebrow">AURUM · Quantitative Modeling & Portfolio Lab</p><p class="brand">PRISM</p>
<p>Allocation, contraintes, chronologie causale et compte rendu autour de Qlib.</p></header><main>
<p class="eyebrow">Démonstration reproductible · Sans ARL</p><h1>Trois composantes fictives, six allocations</h1>
<div class="notice"><strong>Données entièrement synthétiques.</strong> Ces chiffres vérifient un parcours logiciel. Ils ne mesurent ni la performance d’une stratégie réelle, ni la validité scientifique sur un portefeuille réel.</div>
''' + '<p>Qlib '+escape(report['qlib_version'])+' réellement appelé · graine '+str(report['seed'])+
        ' · '+str(report['observations_per_series'])+' observations par série.</p><section><h2>Allocations et trajectoires synthétiques</h2>'+ \
        '<p>Poids à la dernière décision, rendement et drawdown composés par PRISM, volatilité par observation. Coûts en unités de NAV initiale.</p>'+ \
        '<div class="table"><table><thead><tr><th>Méthode</th><th>Poids des composantes</th><th>Cash</th><th>Rendement fictif</th><th>Drawdown NAV</th><th>Volatilité / obs.</th><th>Rotation L1</th><th>Coûts</th></tr></thead><tbody>'+''.join(rows)+ \
        '</tbody></table></div></section><section><h2>Mesures Qlib et conventions</h2>'+ \
        '<div class="table"><table><thead><tr><th>Méthode</th><th>Moyenne / obs.</th><th>Écart-type / obs.</th><th>Annualisation linéaire</th><th>Ratio référence zéro</th><th>Drawdown arithmétique</th></tr></thead><tbody>'+''.join(risk_rows)+'</tbody></table></div>'+ \
        '<p>Les JSON détaillent moyenne, écart-type, rendement annualisé linéaire, ratio de référence zéro et drawdown arithmétique de Qlib. Ce ratio n’est pas présenté comme un Sharpe ; l’annualisation n’est pas un CAGR. La fréquence fictive est explicitement fixée à 2 190 observations/an.</p>'+ \
        '<h2>Mesures non calculables ou non validées</h2><ul>'+unavailable+'</ul></section>'+ \
        '<section><h2>Preuve des appels Qlib</h2><p>Comptage des entrées dans les fonctions de la bibliothèque installée, sans double ni remplacement.</p><pre>'+escape(trace)+'</pre></section></main>'+ \
        '<footer>PRISM : code AURUM, usage personnel privé non commercial gratuit ; commerce sur accord écrit. Qlib et les autres dépendances conservent leurs licences.</footer></html>')


def write_results(folder, frame, outputs, report):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False),encoding='utf-8')
    frame.to_csv(folder/'synthetic-series.csv',index=False,float_format='%.17g',lineterminator='\n')
    for name,path in outputs.items():
        path.to_csv(folder/(name.lower()+'-nav.csv'),index=False,float_format='%.17g',lineterminator='\n')
    (folder/'review.html').write_text(render_html(report),encoding='utf-8')

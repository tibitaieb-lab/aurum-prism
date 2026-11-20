# AURUM PRISM — Quantitative Modeling & Portfolio Lab

PRISM ajoute une couche de laboratoire de portefeuille autour de **Qlib** :
contrats de rendements, chronologie explicite de l’information, contraintes
d’allocation, cash, rééquilibrages, coûts, calcul de NAV et rapport vérifiable.
Il ne prétend pas remplacer Qlib ni valider automatiquement une stratégie.

Cette version publique reprend le **moteur de calcul existant de PRISM**.
Elle fonctionne **sans ARL**, sans portefeuille réel et sans corpus AURUM DATA.
Le portefeuille de démonstration comporte trois composantes fictives :
`DEMO_AZUR`, `DEMO_CORAIL`, `DEMO_JADE`. Leurs rendements sont générés par une
graine fixe, pas par des stratégies ou des backtests réels.

## Installation vérifiée

Prérequis : **Windows x64 et Python 3.12**. Depuis PowerShell, à la racine du dépôt :

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-public.lock.txt
.\.venv\Scripts\python.exe -m pip check
```

Le verrou contient les versions réellement installées pour cette démonstration,
dont **pyqlib 0.9.7, NumPy 2.2.6 et pandas 2.3.3**. La distribution Qlib déclare
un ensemble de dépendances conséquent, notamment MLflow et Jupyter, même si
leurs services et interfaces ne sont pas utilisés ici. L’installation initiale
télécharge ces paquets depuis PyPI ; le calcul n’accède pas au réseau.

Aucun runtime, environnement Python, réglage personnel, donnée de marché ni
bibliothèque de l’installation privée n’est inclus dans le dépôt. Aucun chemin
sur un lecteur particulier n’est requis. Les bibliothèques sont installées
séparément dans `.venv`.

## Lancer l’exemple

```powershell
.\.venv\Scripts\python.exe -I -B tools\demo.py
```

Ouvrez ensuite **`reports/public-demo/review.html`**, ou double-cliquez sur
`LANCER_PRISM_DEMO.cmd` après installation. La revue HTML est autonome, sans
serveur ni ressources externes.

Autres commandes :

```powershell
.\.venv\Scripts\python.exe -I -B tools\demo.py --output reports\autre-demo --observations 240
.\.venv\Scripts\python.exe -I -B tools\run_public_checks.py
```

Les sorties générées restent sous `reports/`, ignoré par Git :

- `result.json` : allocations, historiques de décision, conventions et mesures ;
- `synthetic-series.csv` : séries fictives avec provenance et empreintes ;
- six fichiers `*-nav.csv` : trajectoires de portefeuille ;
- `review.html` : synthèse lisible des allocations, risques et appels Qlib.

La graine **5051729**, les dates synthétiques, les trois profils de bruit et le
générateur sont fournis dans `examples/synthetic_portfolio.py`. L’exemple utilise
240 observations de 4 heures par série. Les identités et la devise sont fictives,
sans conversion de prix, de devise réelle ou de multiplicateur de contrat.

## Parcours conservé et appels Qlib réels

Le wrapper public appelle `portfolio_lab.simulate_certification`, le chemin
existant prévu pour les fixtures synthétiques. Il ne fabrique pas les certificats
de production requis par `run_portfolio`, et n’ouvre pas l’installation ARL.

Six méthodes sont exécutées : MANUAL, EQUAL_WEIGHT, INVERSE_VOLATILITY,
MINIMUM_VARIANCE, MEAN_VARIANCE et RISK_PARITY. Les trois dernières appellent
réellement les objectifs de `qlib.contrib.strategy.optimizer.PortfolioOptimizer`.
La covariance utilise `ShrinkCovEstimator` de Qlib (shrinkage LW). Les mesures
Qlib viennent de `qlib.contrib.evaluate.risk_analysis`.

PRISM conserve sa sous-classe contrôlée : elle ajoute les bornes et le contrôle
du solveur SciPy SLSQP sans remplacer les objectifs Qlib. Elle refuse les sorties
non faisables et contrôle la stationnarité ou l’égalité des contributions au risque.
Il n’y a pas de réallocation de secours silencieuse.

La preuve d’exécution est un relevé des entrées dans les fonctions de la
**bibliothèque Qlib installée**, sans mock et sans remplacement de ses méthodes.
Avec les paramètres par défaut, `result.json` contient :

| Appel Qlib observé | Nombre |
| --- | ---: |
| Optimiseur minimum variance `_optimize_gmv` | 8 |
| Optimiseur moyenne-variance `_optimize_mvo` | 8 |
| Optimiseur risk parity `_optimize_rp` | 8 |
| Prédiction de covariance `riskmodel.base.predict` | 24 |
| `risk_analysis` | 6 |

Les six fichiers Qlib attendus par l’adaptateur sont vérifiés par SHA-256 avec
`QLIB_INTEGRATION_V1.json`. Une autre version ou des fichiers modifiés entraînent
un refus, pas une validation implicite.

## Risques, conventions et limites

Le rapport expose les poids de la dernière décision, cash, rendement composé,
drawdown de NAV, volatilité par observation, rotation L1, coûts, corrélations,
covariances et diagnostics d’optimisation. Les décisions utilisent les données
disponibles à la clôture, avant décision et application à l’intervalle suivant.

Les mesures Qlib sont distinguées des mesures PRISM : son annualisation linéaire
n’est pas un CAGR, son ratio à référence zéro n’est pas présenté comme un Sharpe,
et son drawdown arithmétique n’est pas le drawdown composé de la NAV PRISM.
La fréquence de **2 190 observations/an** est une convention fictive explicite
(365 × 6), sans calendrier de marché réel.

**Sharpe et Sharpe déflaté restent NON_CALCULABLE** : aucune convention de taux
sans risque, aucun historique complet de sélection ni justification IID ne sont
fournis. L’exposition aux instruments sous-jacents n’est pas calculable à partir
de seuls rendements de composantes. L’estimateur OAS reste désactivé selon le
contrôle existant ; aucun estimateur de remplacement n’est inventé.

## Contrôles effectués

La suite comporte **20 tests** avec calculs Qlib réels :

- reproductibilité des séries et présence des appels Qlib ;
- poids, cash, bornes et diagnostics KKT/contributions au risque ;
- invariance à la mutation du futur et à la troncature de l’historique ;
- ordre des événements et application des poids à l’intervalle suivant ;
- NAV, coûts et dérive des poids vérifiés sur un calcul manuel ;
- refus des séries manquantes, non finies, désordonnées, dupliquées ou altérées ;
- refus des contraintes impossibles et publications tardives ;
- solutions diagonales connues pour variance minimale et risk parity ;
- absence de faux certificat, de fausse mesure de risque ou d’import ARL.

L’installation, la démo et les tests ont aussi été exécutés depuis une copie
**recréée par Git dans un autre dossier**, avec un nouvel environnement Python.
Les fichiers du parcours sont protégés contre les conversions de fins de ligne
par `.gitattributes`, et leurs empreintes sont comparées après extraction.

Les essais d’autonomie ont utilisé Python et les dépendances sur `C:`, avec un
audit refusant les accès aux installations privées sur `F:` et `G:`. La garde
réseau Python est diagnostique ; ce n’est pas une isolation système contre du
code hostile. Les tests incluent une tentative DNS factice volontairement refusée.
Le lanceur CMD est relu ; le calcul Python et la revue HTML sont vérifiés sans
présumer qu’un double-clic Windows a été testé.

## État de la validation scientifique

**Aucune validation scientifique sur portefeuille réel n’est établie par cette
version publique.** Les résultats sont des contrôles logiciels synthétiques.
Les anciennes mentions de certification de l’installation ne sont pas reprises
comme preuve publique de performance. La génération de stratégies, l’entraînement
prédictif, les marchés, les backtests réels et l’admission ARL ne sont pas testés ici.

## Code PRISM et composants tiers

- `aurum_qlib_lab/` : code AURUM/PRISM du moteur, repris sans changement ;
- `QLIB_INTEGRATION_V1.json` : version et empreintes Qlib attendues ;
- `examples/` : générateur synthétique existant, adapté aux identités fictives ;
- `public_prism/`, `tools/`, `tests/` : parcours public, preuve des appels,
  présentation et contrôles ;
- Qlib, NumPy, pandas, SciPy, PyArrow et les dépendances du verrou : composants
  tiers installés séparément. Aucun code Qlib, binaire ou environnement privé
  n’est recopié dans le dépôt.

`LICENSE.txt` accorde au code AURUM un **usage personnel, privé et non commercial
gratuit**. L’exploitation commerciale, même interne, nécessite un **accord écrit
préalable** du titulaire des droits, comme pour ARKS et ADAM. Les autres droits
restent réservés ; ce n’est pas une licence open source.

Cette restriction AURUM ne s’applique pas à Qlib ni aux autres composants tiers.
[Qlib 0.9.7 est sous licence MIT, copyright Microsoft](https://github.com/microsoft/qlib/blob/v0.9.7/LICENSE).
Le texte officiel et ses mentions sont conservés dans `LICENSES/QLIB-MIT.txt`,
même si son code est installé comme dépendance et non redistribué ici.
`THIRD_PARTY_NOTICES.md` identifie les bibliothèques et leurs mentions.

Ne versionnez pas de stratégies, données ou résultats réels, de configurations
personnelles, de journaux ni de secrets. Le dépôt ne reprend ni le workspace,
ni les audits privés, ni les données ou modèles, ni l’historique Git d’origine.

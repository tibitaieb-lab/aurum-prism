# Composants tiers

Le dépôt contient le code AURUM/PRISM et le démonstrateur. Les bibliothèques sont
installées séparément depuis PyPI ; aucun code ni binaire de Qlib n’est redistribué
dans le dépôt. La licence d’usage personnel et non commercial AURUM ne s’étend pas
aux composants tiers, qui conservent leurs propres droits et licences.

## Qlib

**Qlib 0.9.7 — Microsoft Corporation — MIT.** Le texte officiel, inchangé,
est conservé dans [LICENSES/QLIB-MIT.txt](LICENSES/QLIB-MIT.txt).
Source : [licence officielle de la version 0.9.7](https://github.com/microsoft/qlib/blob/v0.9.7/LICENSE).
Les modules tiers utilisés sont PortfolioOptimizer, ShrinkCovEstimator et
risk_analysis. Les objectifs Qlib restent ceux de la bibliothèque installée ;
la sous-classe contrôlant le solveur et les contraintes est du code PRISM.

Les avertissements d’import émis par la dépendance Gym de Qlib ne sont pas supprimés.
Le parcours public ne fait aucun entraînement ou calcul de reinforcement learning.

## Mentions des bibliothèques numériques directes

Les textes ci-dessous sont copiés sans modification depuis les distributions
effectivement installées. Aucun binaire de ces bibliothèques n’est livré ici.

- numpy : [LICENSE.txt](LICENSES/numpy/LICENSE.txt)
- pandas : [LICENSE](LICENSES/pandas/LICENSE)
- scipy : [LICENSE.txt](LICENSES/scipy/LICENSE.txt)
- pyarrow : [LICENSE.txt](LICENSES/pyarrow/licenses/LICENSE.txt), [NOTICE.txt](LICENSES/pyarrow/licenses/NOTICE.txt)
- scikit-learn : [COPYING](LICENSES/scikit-learn/licenses/COPYING)

## Environnement vérifié et dépendances transitives

Cette liste suit le verrou de l’installation publique ; elle ne signifie pas que
toutes les fonctions de ces paquets sont exercées dans la démonstration. Les licences
indiquées sont les déclarations fournies par les distributions. Leurs paquets
installés conservent leurs mentions et éventuelles licences de composants embarqués.

| Bibliothèque | Version | Licence déclarée |
| --- | --- | --- |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache 2.0 |
| alembic | 1.20.1 | MIT |
| annotated-doc | 0.0.7 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| argon2-cffi | 25.1.0 | MIT |
| argon2-cffi-bindings | 26.2.0 | MIT |
| arrow | 1.4.0 | Apache Software License |
| asttokens | 3.0.2 | Apache 2.0 |
| async-lru | 2.4.0 | MIT License |
| attrs | 26.1.0 | MIT |
| babel | 2.18.0 | BSD-3-Clause |
| beautifulsoup4 | 4.15.0 | MIT License |
| bleach | 6.4.0 | Apache Software License |
| blinker | 1.9.0 | MIT License |
| cachetools | 7.3.3 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.2 | MIT |
| clarabel | 0.11.1 | Apache-2.0 |
| click | 8.5.1 | BSD-3-Clause |
| cloudpickle | 3.1.3 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| comm | 0.2.3 | BSD License |
| contourpy | 1.4.0 | BSD-3-Clause |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| cvxpy | 1.9.3 | Apache-2.0 |
| cycler | 0.12.1 | BSD License |
| databricks-sdk | 0.169.0 | Apache Software License |
| debugpy | 1.8.22 | MIT |
| defusedxml | 0.7.1 | PSFL |
| dill | 0.4.1 | BSD-3-Clause |
| dnspython | 2.9.2 | ISC |
| docker | 7.2.0 | Apache-2.0 |
| executing | 2.3.0 | MIT |
| fastapi | 0.165.0 | MIT |
| fastjsonschema | 2.22.3 | BSD-3-Clause |
| filelock | 4.2.12 | MIT |
| fire | 0.7.1 | Apache-2.0 |
| Flask | 3.1.3 | BSD-3-Clause |
| flask-cors | 6.0.5 | MIT |
| fonttools | 4.68.0 | MIT |
| fqdn | 1.6.0 | MPL-2.0 |
| frozenlist | 1.8.0 | Apache-2.0 |
| gitdb | 4.0.12 | BSD License |
| GitPython | 3.2.1 | BSD-3-Clause |
| google-auth | 2.62.2 | Apache 2.0 |
| graphene | 3.4.3 | MIT |
| graphql-core | 3.2.14 | MIT license |
| graphql-relay | 3.2.0 | MIT |
| gym | 0.26.2 | MIT |
| gym-notices | 0.1.0 | MIT License |
| h11 | 0.16.0 | MIT |
| highspy | 1.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| huey | 3.5.4 | Voir les mentions de la distribution |
| idna | 3.20 | BSD-3-Clause |
| importlib_metadata | 10.2.0 | Apache-2.0 |
| ipykernel | 7.4.0 | BSD-3-Clause |
| ipython | 9.18.1 | BSD-3-Clause |
| ipython_pygments_lexers | 1.1.1 | BSD License |
| ipywidgets | 8.1.9 | BSD 3-Clause License |
| isoduration | 20.11.0 | UNKNOWN |
| itsdangerous | 2.2.0 | BSD License |
| jedi | 0.20.1 | MIT |
| Jinja2 | 3.1.6 | BSD License |
| joblib | 1.6.0 | BSD-3-Clause |
| json5 | 0.17.3 | Apache-2.0 |
| jsonpointer | 3.12 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| jupyter | 1.1.1 | BSD |
| jupyter-console | 6.6.3 | BSD License |
| jupyter-events | 0.12.1 | BSD License |
| jupyter-lsp | 2.3.1 | BSD-3-Clause |
| jupyter_builder | 1.3.0 | Apache-2.0 AND BSD-2-Clause AND BSD-3-Clause AND ISC AND MIT |
| jupyter_client | 8.10.0 | BSD License |
| jupyter_core | 5.9.1 | BSD-3-Clause |
| jupyter_server | 2.21.1 | BSD License |
| jupyter_server_terminals | 0.5.4 | BSD License |
| jupyterlab | 4.6.6 | BSD License |
| jupyterlab_pygments | 0.3.0 | BSD License |
| jupyterlab_server | 2.28.1 | BSD License |
| jupyterlab_widgets | 3.0.17 | BSD License |
| kiwisolver | 1.5.1 | BSD License |
| lark | 1.3.1 | MIT |
| lazy-importer | 0.1.0 | Apache-2.0 |
| lightgbm | 4.7.0 | MIT |
| loguru | 0.8.0 | MIT License |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| matplotlib | 3.11.2 | Python Software Foundation License |
| matplotlib-inline | 0.2.2 | BSD-3-Clause |
| mistune | 3.4.0 | BSD-3-Clause |
| mlflow | 3.18.0 | Apache Software License |
| mlflow-skinny | 3.18.0 | Apache Software License |
| mlflow-tracing | 3.18.0 | Apache Software License |
| multidict | 7.2.1 | Apache-2.0 |
| narwhals | 2.29.0 | MIT |
| nbclient | 0.11.0 | BSD License |
| nbconvert | 7.17.2 | BSD License |
| nbformat | 5.11.1 | BSD License |
| nest-asyncio2 | 1.7.4 | BSD |
| notebook | 7.6.5 | BSD License |
| notebook_shim | 0.2.4 | BSD License |
| numpy | 2.2.6 | BSD License |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| opentelemetry-proto | 1.45.2 | Apache-2.0 |
| opentelemetry-sdk | 1.45.2 | Apache-2.0 |
| opentelemetry-semantic-conventions | 0.66b2 | Apache-2.0 |
| osqp | 1.1.3 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pandas | 2.3.3 | BSD License |
| pandocfilters | 1.5.1 | BSD-3-Clause |
| parso | 0.8.7 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| platformdirs | 4.14.7 | MIT |
| prettytable | 3.19.0 | BSD-3-Clause |
| prometheus_client | 0.26.0 | Apache-2.0 AND BSD-2-Clause |
| prompt_toolkit | 3.0.53 | BSD License |
| propcache | 0.5.4 | Apache-2.0 |
| protobuf | 7.36.2 | 3-Clause BSD License |
| psutil | 7.2.2 | BSD-3-Clause |
| pure_eval | 0.2.4 | MIT |
| pyarrow | 26.0.1 | Apache-2.0 |
| pyasn1 | 0.6.5 | BSD-2-Clause |
| pyasn1_modules | 0.4.2 | BSD |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.4 | MIT |
| pydantic-settings | 2.16.3 | MIT |
| pydantic_core | 2.50.5 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pymongo | 4.20.1 | Apache-2.0 |
| pyparsing | 3.3.3 | MIT |
| pyqlib | 0.9.7 | MIT License |
| python-dateutil | 2.9.0.post0 | Dual License |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-json-logger | 4.2.0 | BSD-2-Clause |
| python-multipart | 0.0.34 | Apache-2.0 |
| python-redis-lock | 4.0.1 | BSD-2-Clause |
| pytz | 2026.6 | MIT |
| pywin32 | 312 | PSF |
| pywinpty | 3.1.2 | MIT License |
| PyYAML | 6.0.3 | MIT |
| pyzmq | 27.3.0 | BSD-3-Clause |
| qdldl | 0.1.9.post1 | Apache 2.0 |
| redis | 8.1.0 | MIT |
| referencing | 0.37.0 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| rfc3339-validator | 0.1.4 | MIT license |
| rfc3986-validator | 0.1.1 | MIT license |
| rfc3987-syntax | 1.1.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| ruamel.yaml | 0.19.1 | MIT |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| scipy | 1.18.1 | BSD License |
| scs | 3.3.2 | MIT License |
| Send2Trash | 2.2.0 | BSD-3-Clause |
| setuptools | 84.2.1 | MIT |
| six | 1.17.0 | MIT |
| skops | 0.16.0 | OSI Approved |
| smmap | 5.0.3 | BSD-3-Clause |
| soupsieve | 4.1.2 | MIT |
| sparsediffpy | 0.6.1 | Apache-2.0 |
| SQLAlchemy | 2.1.9 | MIT |
| sqlparse | 0.6.1 | BSD License |
| stack-data | 0.6.3 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| termcolor | 3.3.0 | MIT |
| terminado | 0.18.1 | BSD License |
| threadpoolctl | 3.8.0 | BSD-3-Clause |
| tinycss2 | 1.5.1 | BSD License |
| tornado | 6.6.1 | Apache-2.0 |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| traitlets | 5.16.1 | BSD License |
| typing-inspection | 0.4.5 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.6 | Apache-2.0 |
| uri-template | 1.3.0 | MIT License |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| waitress | 3.0.2 | ZPL 2.1 |
| wcwidth | 0.9.4 | MIT License |
| webcolors | 25.10.0 | BSD-3-Clause |
| webencodings | 0.6.1 | BSD License |
| websocket-client | 1.9.2 | Apache-2.0 |
| Werkzeug | 3.1.9 | BSD-3-Clause |
| widgetsnbextension | 4.0.16 | BSD 3-Clause License |
| win32_setctime | 1.2.1 | MIT license |
| yarl | 1.25.1 | Apache-2.0 |
| zipp | 4.1.2 | MIT |

"""CLI for a synthetic-only calculation through the existing PRISM engine."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from public_prism.offline import install
install()

def main():
    parser=argparse.ArgumentParser(description='PRISM — portefeuille fictif avec appels Qlib réels')
    parser.add_argument('--output',type=Path,default=ROOT/'reports/public-demo')
    parser.add_argument('--observations',type=int,default=240)
    args=parser.parse_args()
    os.environ['MPLCONFIGDIR']=str(args.output.resolve()/'_cache/matplotlib')
    from public_prism.demo import run_demo,write_results
    frame,outputs,report=run_demo(args.observations)
    write_results(args.output,frame,outputs,report)
    print(json.dumps({'status':'PASS_SYNTHETIC_ONLY','qlib_version':report['qlib_version'],
        'methods':list(report['results']),'qlib_calls':report['qlib_calls'],
        'review':str((args.output/'review.html').resolve())},ensure_ascii=True))
    return 0

if __name__=='__main__':raise SystemExit(main())

"""Bounded public-clock probe; no clock/service changes or account access."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from scripts.run_hybrid_clock_observer import probes


async def run(output):
    if not output.is_relative_to(ROOT/'outputs/hybrid_delivery') or output.exists():raise ValueError('New independent output required')
    output.mkdir(parents=True,exist_ok=False)
    async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
        rows=await probes(client)
    (output/'clock_probes.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(rows))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    asyncio.run(run((ROOT/a.output).resolve()))

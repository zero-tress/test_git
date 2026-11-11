"""Query a versioned semantic skill."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.knowledge_base import query
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("skill_id")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1]/"knowledge_base")
    ap.add_argument("--version")
    args=ap.parse_args()
    print(json.dumps(query(args.root,args.skill_id,args.version),ensure_ascii=False,indent=2))
if __name__=="__main__": main()

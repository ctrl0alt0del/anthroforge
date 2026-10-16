"""Isolated native FLOW, tracing and Bi-MDF process boundary."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.topology.quadwild import run

if __name__ == "__main__": run(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))

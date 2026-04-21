from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .metrics import score_trades, summarize_by_scenario
from .reporting import evaluate_feasibility, write_feasibility_markdown, write_json
from .simulator import run_backtest
from .sweeps import run_parameter_sweep
from .validation import manual_replay_sample


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def cmd_run(config_path: str) -> int:
    cfg = load_config(config_path)
    out_dir = Path(cfg.output.out_dir)
    stamp = _timestamp()

    trades, sims = run_backtest(cfg)
    scored = score_trades(trades, sims, cfg)
    summary = summarize_by_scenario(scored, cfg)
    feas = evaluate_feasibility(summary, cfg)
    replay = manual_replay_sample(scored, sims, cfg, sample_size=25, seed=42)
    replay_match_rate = float(replay["match"].mean()) if not replay.empty else 1.0

    out_dir.mkdir(parents=True, exist_ok=True)
    scored.to_csv(out_dir / f"trades_{stamp}.csv", index=False)
    replay.to_csv(out_dir / f"manual_replay_sample_{stamp}.csv", index=False)
    write_json(out_dir / f"summary_{stamp}.json", summary)
    write_json(
        out_dir / f"feasibility_{stamp}.json",
        {**feas, "manual_replay_match_rate": replay_match_rate},
    )
    write_feasibility_markdown(out_dir / "feasibility_report.md", feas, summary)
    return 0


def cmd_sweep(config_path: str) -> int:
    cfg = load_config(config_path)
    out_dir = Path(cfg.output.out_dir)
    stamp = _timestamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    df = run_parameter_sweep(cfg)
    df.to_csv(out_dir / f"sweep_results_{stamp}.csv", index=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Synthetic spike backtest CLI")
    sub = p.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run single backtest with config")
    p_run.add_argument("--config", required=True, help="Path to YAML config")

    p_sweep = sub.add_parser("sweep", help="Run parameter sweep")
    p_sweep.add_argument("--config", required=True, help="Path to YAML config")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return cmd_run(args.config)
    if args.command == "sweep":
        return cmd_sweep(args.config)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

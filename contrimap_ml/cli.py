from __future__ import annotations

import argparse
import json
import logging
import os

from dotenv import load_dotenv

from .github_ingest import GitHubRateLimitError, collect_repository
from .models import ContriMapModels, train_models


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="ContriMap historical ingestion and ML training")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("owner")
    ingest.add_argument("repo")
    ingest.add_argument("--output", default="data")
    ingest.add_argument("--max-issues", type=int)
    train = subparsers.add_parser("train")
    train.add_argument("dataset")
    train.add_argument("--output", default="artifacts")
    predict = subparsers.add_parser("predict")
    predict.add_argument("artifacts")
    predict.add_argument("title")
    predict.add_argument("--body", default="")
    predict.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if args.command == "ingest":
        try:
            print(collect_repository(args.owner, args.repo, args.output, os.getenv("GITHUB_TOKEN"), args.max_issues))
        except GitHubRateLimitError as error:
            parser.exit(1, f"GitHub rate limit exceeded. {error}\n")
    elif args.command == "train":
        print(json.dumps(train_models(args.dataset, args.output), indent=2))
    else:
        print(json.dumps(ContriMapModels.load(args.artifacts).predict(args.title, args.body, top_k=args.top_k), indent=2))


if __name__ == "__main__":
    main()

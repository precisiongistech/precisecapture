"""Write the sync/attachment examples to contract/examples/*.json (mock smoke test, Selorm)."""

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from precisecapture.attachments.schemas import ATTACHMENT_UPLOAD_EXAMPLE
from precisecapture.sync.schemas import (
    PULL_RESPONSE_EXAMPLE,
    PUSH_REQUEST_EXAMPLE,
    PUSH_RESPONSE_EXAMPLE,
)

EXAMPLES: dict[str, dict[str, Any]] = {
    "push-request": PUSH_REQUEST_EXAMPLE,
    "push-response": PUSH_RESPONSE_EXAMPLE,
    "pull-response": PULL_RESPONSE_EXAMPLE,
    "attachment-upload": ATTACHMENT_UPLOAD_EXAMPLE,
}


class Command(BaseCommand):
    help = "Export the contract example documents as JSON files."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--output", required=True, help="Directory for the JSON files")

    def handle(self, *args: Any, **options: Any) -> None:
        out = Path(options["output"])
        out.mkdir(parents=True, exist_ok=True)
        for name, example in EXAMPLES.items():
            (out / f"{name}.json").write_text(
                json.dumps(example, indent=2) + "\n", encoding="utf-8"
            )
        self.stdout.write(f"wrote {len(EXAMPLES)} example files to {out}")

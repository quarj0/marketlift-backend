from pathlib import Path

from django.core.management.base import BaseCommand

from marketlift.graphql.schema import schema


class Command(BaseCommand):
    help = "Export the current Strawberry GraphQL schema to an SDL file."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default="docs/schema.graphql")

    def handle(self, *args, **options):
        path = Path(options["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(schema.as_str(), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"GraphQL schema written to {path}"))

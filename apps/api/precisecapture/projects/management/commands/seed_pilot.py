"""
seed_pilot: the demo organisation and the Western North Farm Mapping project.

Idempotent: re-running updates nothing that exists and never creates duplicates.
Users: admin@pilot.local, manager@pilot.local, collector1@pilot.local, collector2@pilot.local,
all with password "pilot-pass-2026" (dev/demo only).
"""

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from precisecapture.accounts.models import User
from precisecapture.common.tenancy import tenant_context
from precisecapture.orgs.models import Membership, Organisation, Role
from precisecapture.projects import schema_services, services
from precisecapture.projects.models import Layer, Project, ProjectMember

DEMO_PASSWORD = "pilot-pass-2026"
ORG_SLUG = "pilot-demo"
PROJECT_NAME = "Western North Farm Mapping"
# Rough extent of Western North Region, Ghana (lon/lat).
EXTENT = Polygon(((-3.3, 5.8), (-2.2, 5.8), (-2.2, 6.9), (-3.3, 6.9), (-3.3, 5.8)), srid=4326)

PEOPLE = [
    ("admin@pilot.local", "Pilot Admin", Role.ADMIN, None),
    ("manager@pilot.local", "Pilot Manager", Role.MANAGER, "manager"),
    ("collector1@pilot.local", "Collector One", Role.COLLECTOR, "collector"),
    ("collector2@pilot.local", "Collector Two", Role.COLLECTOR, "collector"),
]


def _example(name: str) -> dict[str, Any]:
    path = Path(settings.SCHEMA_DIR) / "examples" / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class Command(BaseCommand):
    help = "Create (idempotently) the demo org, users and the Western North pilot project."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--password", default=DEMO_PASSWORD, help="Password for the demo users")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        password: str = options["password"]
        org, created = Organisation.objects.get_or_create(
            slug=ORG_SLUG,
            defaults={
                "name": "Pilot Demo Cooperative",
                "country": "GH",
                "settings": {
                    "capture_defaults": {"gps": {"maxAccuracyMeters": 8, "onPoorAccuracy": "warn"}}
                },
            },
        )
        self._log(f"organisation {org.slug}", created)

        users: dict[str, User] = {}
        for email, name, org_role, _ in PEOPLE:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email=email, password=password, name=name)
                self._log(f"user {email}", True)
            else:
                self._log(f"user {email}", False)
            Membership.objects.get_or_create(user=user, org=org, defaults={"role": org_role})
            users[email] = user

        with tenant_context(org.id):
            project = Project.objects.filter(name=PROJECT_NAME).first()
            if project is None:
                project = services.create_project(
                    org,
                    users["admin@pilot.local"],
                    {
                        "name": PROJECT_NAME,
                        "description": "Farm boundary and centroid mapping for EUDR-ready exports.",
                        "extent": json.loads(EXTENT.geojson),
                        "status": Project.Status.ACTIVE,
                        "settings": {"capture_profile": {"stream": {"intervalMeters": 3}}},
                    },
                )
                self._log("project", True)
            else:
                self._log("project", False)

            for email, _, _, project_role in PEOPLE:
                if (
                    project_role
                    and not ProjectMember.objects.filter(
                        project=project, user=users[email]
                    ).exists()
                ):
                    services.add_member(project, {"user_id": users[email].id, "role": project_role})

            farmers = self._layer(
                project, "Farmers", "lyr_farmers", "none", {}, _example("farmers.layer-schema.json")
            )
            self._layer(
                project,
                "Farms",
                "lyr_farms",
                "polygon",
                _example("farms.capture-profile.json"),
                _example("farms.layer-schema.json"),
            )
            project.refresh_from_db()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Pilot ready: org {org.id}, project {project.id} "
                    f"(config_version {project.config_version}); layers {farmers.key}, lyr_farms. "
                    f"Login e.g. manager@pilot.local / {password}"
                )
            )

    def _layer(
        self,
        project: Project,
        name: str,
        key: str,
        geometry_type: str,
        capture_profile: dict[str, Any],
        schema: dict[str, Any],
    ) -> Layer:
        layer = Layer.objects.filter(project=project, key=key).first()
        if layer is None:
            layer = services.create_layer(
                project,
                {
                    "name": name,
                    "key": key,
                    "geometry_type": geometry_type,
                    "capture_profile": capture_profile,
                },
            )
            self._log(f"layer {key}", True)
        else:
            self._log(f"layer {key}", False)
        if layer.current_schema_version == 0:
            doc = {
                k: v for k, v in schema.items() if k not in ("version", "layerId", "schemaVersion")
            }
            schema_services.save_draft(layer, doc)
            version, _ = schema_services.publish_schema(
                layer, User.objects.get(email="admin@pilot.local")
            )
            self._log(f"schema {key} v{version.version}", True)
        return layer

    def _log(self, what: str, created: bool) -> None:
        self.stdout.write(f"  {'created' if created else 'exists '}  {what}")

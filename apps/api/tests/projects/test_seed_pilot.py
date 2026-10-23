import pytest
from django.core.management import call_command

from precisecapture.accounts.models import User
from precisecapture.common.tenancy import tenant_context
from precisecapture.orgs.models import Membership, Organisation
from precisecapture.projects.models import Layer, LayerSchemaVersion, Project, ProjectMember
from precisecapture.projects.schema_services import build_bundle

pytestmark = pytest.mark.django_db


def test_seed_pilot_is_idempotent(capsys):
    call_command("seed_pilot")
    call_command("seed_pilot")
    org = Organisation.objects.get(slug="pilot-demo")
    assert Organisation.objects.count() == 1
    assert User.objects.filter(email__endswith="@pilot.local").count() == 4
    assert Membership.objects.filter(org=org).count() == 4
    with tenant_context(org.id):
        project = Project.objects.get(name="Western North Farm Mapping")
        assert Project.objects.count() == 1
        assert sorted(Layer.objects.values_list("key", flat=True)) == ["lyr_farmers", "lyr_farms"]
        assert LayerSchemaVersion.objects.count() == 2  # one published version each, not four
        assert ProjectMember.objects.filter(project=project).count() == 3
        farms = Layer.objects.get(key="lyr_farms")
        assert (
            farms.current_schema_version == 1
            and farms.capture_profile["autoClose"]["locked"] is True
        )
        manager = Membership.objects.get(user__email="manager@pilot.local", org=org)
        bundle = build_bundle(project, manager, "manager")
        assert [layer["key"] for layer in bundle["layers"]] == ["lyr_farmers", "lyr_farms"]
        assert bundle["layers"][1]["capture_profile"]["gps"]["maxAccuracyMeters"] == 5
        assert bundle["layers"][1]["schema"]["fields"][0]["relation"]["layer"] == "lyr_farmers"
    out = capsys.readouterr().out
    assert out.count("Pilot ready") == 2
    assert User.objects.get(email="manager@pilot.local").check_password("pilot-pass-2026")

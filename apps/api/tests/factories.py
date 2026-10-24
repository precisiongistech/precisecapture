"""factory_boy factories shared by the test suite."""

import uuid

import factory
from factory.django import DjangoModelFactory

from precisecapture.accounts.models import Device, User
from precisecapture.attachments.models import Attachment
from precisecapture.features.models import (
    Feature,
    FeatureHistory,
    FeatureRelation,
    RawTrack,
    VertexMeta,
)
from precisecapture.orgs.models import Membership, Organisation, Role
from precisecapture.projects.models import (
    GeometryType,
    Layer,
    LayerSchemaVersion,
    LayerTemplate,
    Project,
    ProjectMember,
    ProjectRole,
)
from precisecapture.sync.models import (
    AppliedChange,
    ChangeLog,
    Conflict,
    ProjectSyncState,
    SyncCursor,
)


class UserFactory(DjangoModelFactory[User]):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.org")
    name = factory.Faker("name")
    password = factory.django.Password("correct horse battery staple")


class PhoneUserFactory(UserFactory):
    email = None
    phone = factory.Sequence(lambda n: f"+23324{n:07d}")


class OrganisationFactory(DjangoModelFactory[Organisation]):
    class Meta:
        model = Organisation

    name = factory.Sequence(lambda n: f"Org {n}")
    slug = factory.LazyAttribute(lambda o: Organisation.unique_slug(o.name))
    country = "GH"


class MembershipFactory(DjangoModelFactory[Membership]):
    class Meta:
        model = Membership

    user = factory.SubFactory(UserFactory)
    org = factory.SubFactory(OrganisationFactory)
    role = Role.COLLECTOR


class DeviceFactory(DjangoModelFactory[Device]):
    class Meta:
        model = Device

    user = factory.SubFactory(UserFactory)
    platform = Device.Platform.ANDROID
    model = "Tecno Spark 10"
    os_version = "13"
    app_version = "0.1.0"


# --- tenant models: pass org= explicitly or create them inside tenant_context(org.id) ---


class ProjectFactory(DjangoModelFactory[Project]):
    class Meta:
        model = Project

    org = factory.SubFactory(OrganisationFactory)
    name = factory.Sequence(lambda n: f"Project {n}")
    status = Project.Status.ACTIVE


class ProjectMemberFactory(DjangoModelFactory[ProjectMember]):
    class Meta:
        model = ProjectMember

    project = factory.SubFactory(ProjectFactory)
    org = factory.LazyAttribute(lambda o: o.project.org)
    user = factory.SubFactory(UserFactory)
    role = ProjectRole.COLLECTOR


class LayerFactory(DjangoModelFactory[Layer]):
    class Meta:
        model = Layer

    project = factory.SubFactory(ProjectFactory)
    org = factory.LazyAttribute(lambda o: o.project.org)
    name = factory.Sequence(lambda n: f"Layer {n}")
    key = factory.Sequence(lambda n: f"lyr_{n}")
    geometry_type = GeometryType.POLYGON


class LayerSchemaVersionFactory(DjangoModelFactory[LayerSchemaVersion]):
    class Meta:
        model = LayerSchemaVersion

    layer = factory.SubFactory(LayerFactory)
    org = factory.LazyAttribute(lambda o: o.layer.org)
    version = 1
    attributes = {"schemaVersion": 1, "fields": [{"key": "name", "type": "text"}]}


class LayerTemplateFactory(DjangoModelFactory[LayerTemplate]):
    class Meta:
        model = LayerTemplate

    org = factory.SubFactory(OrganisationFactory)
    name = factory.Sequence(lambda n: f"Template {n}")
    geometry_type = GeometryType.POINT
    attributes = {"schemaVersion": 1, "fields": [{"key": "name", "type": "text"}]}


SQUARE_WKT = "SRID=4326;POLYGON((-2.5 6.2, -2.499 6.2, -2.499 6.201, -2.5 6.201, -2.5 6.2))"


class FeatureFactory(DjangoModelFactory[Feature]):
    class Meta:
        model = Feature

    layer = factory.SubFactory(LayerFactory)
    project = factory.LazyAttribute(lambda o: o.layer.project)
    org = factory.LazyAttribute(lambda o: o.layer.org)
    geometry_type = factory.LazyAttribute(lambda o: o.layer.geometry_type)
    geom = factory.LazyAttribute(
        lambda o: SQUARE_WKT if o.layer.geometry_type == "polygon" else None
    )
    attributes = factory.LazyFunction(dict)
    schema_version = 1


class FeatureHistoryFactory(DjangoModelFactory[FeatureHistory]):
    class Meta:
        model = FeatureHistory

    feature = factory.SubFactory(FeatureFactory)
    org = factory.LazyAttribute(lambda o: o.feature.org)
    version = 1
    change_type = "create"
    status = "submitted"


class FeatureRelationFactory(DjangoModelFactory[FeatureRelation]):
    class Meta:
        model = FeatureRelation

    from_feature = factory.SubFactory(FeatureFactory)
    to_feature = factory.SubFactory(FeatureFactory)
    org = factory.LazyAttribute(lambda o: o.from_feature.org)
    attribute_key = "farmer"


class RawTrackFactory(DjangoModelFactory[RawTrack]):
    class Meta:
        model = RawTrack

    feature = factory.SubFactory(FeatureFactory)
    org = factory.LazyAttribute(lambda o: o.feature.org)
    points = [[-2.5, 6.2, 3.1, 1760000000000]]
    point_count = 1


class VertexMetaFactory(DjangoModelFactory[VertexMeta]):
    class Meta:
        model = VertexMeta

    feature = factory.SubFactory(FeatureFactory)
    org = factory.LazyAttribute(lambda o: o.feature.org)
    vertex_index = 0
    accuracy_m = 3.1


class ProjectSyncStateFactory(DjangoModelFactory[ProjectSyncState]):
    class Meta:
        model = ProjectSyncState

    project = factory.SubFactory(ProjectFactory)
    org = factory.LazyAttribute(lambda o: o.project.org)


class ChangeLogFactory(DjangoModelFactory[ChangeLog]):
    class Meta:
        model = ChangeLog

    project = factory.SubFactory(ProjectFactory)
    org = factory.LazyAttribute(lambda o: o.project.org)
    seq = factory.Sequence(lambda n: n + 1)
    entity_id = factory.LazyFunction(uuid.uuid4)
    op = "create"
    feature_version = 1


class AppliedChangeFactory(DjangoModelFactory[AppliedChange]):
    class Meta:
        model = AppliedChange

    project = factory.SubFactory(ProjectFactory)
    org = factory.LazyAttribute(lambda o: o.project.org)
    change_id = factory.LazyFunction(uuid.uuid4)
    result = {"status": "accepted"}


class SyncCursorFactory(DjangoModelFactory[SyncCursor]):
    class Meta:
        model = SyncCursor

    project = factory.SubFactory(ProjectFactory)
    org = factory.LazyAttribute(lambda o: o.project.org)
    device = factory.SubFactory(DeviceFactory)


class ConflictFactory(DjangoModelFactory[Conflict]):
    class Meta:
        model = Conflict

    feature = factory.SubFactory(FeatureFactory)
    project = factory.LazyAttribute(lambda o: o.feature.project)
    org = factory.LazyAttribute(lambda o: o.feature.org)
    reason = "field_overlap"
    server_version = 2
    local_payload = {}
    server_payload = {}


class AttachmentFactory(DjangoModelFactory[Attachment]):
    class Meta:
        model = Attachment

    feature = factory.SubFactory(FeatureFactory)
    project = factory.LazyAttribute(lambda o: o.feature.project)
    org = factory.LazyAttribute(lambda o: o.feature.org)
    field_key = "photos"
    content_type = "image/jpeg"
    size = 1024
    checksum_sha256 = "a" * 64
    storage_key = factory.LazyAttribute(
        lambda o: (
            f"org/{o.feature.org_id}/project/{o.feature.project_id}/feature/{o.feature.id}/{uuid.uuid4()}.jpg"
        )
    )
    part_size = 8 * 1024 * 1024

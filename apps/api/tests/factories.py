"""factory_boy factories shared by the test suite."""

import factory
from factory.django import DjangoModelFactory

from precisecapture.accounts.models import Device, User
from precisecapture.orgs.models import Membership, Organisation, Role


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

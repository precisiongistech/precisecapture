from django.apps import apps
from django.contrib import admin

from precisecapture.common.admin import PlatformModelAdmin
from precisecapture.orgs.models import Invitation, Membership, Organisation


class OrganisationAdmin(PlatformModelAdmin):
    list_display = ("name", "slug", "country", "plan", "created_at")
    list_filter = ("plan", "country")
    search_fields = ("name", "slug")
    readonly_fields = ("id", "created_at", "updated_at")


class MembershipAdmin(PlatformModelAdmin):
    list_display = ("user", "org", "role", "version", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email", "user__phone", "org__name")
    readonly_fields = ("id", "created_at", "updated_at")


class InvitationAdmin(PlatformModelAdmin):
    list_display = ("org", "email", "phone", "role", "expires_at", "accepted_at", "revoked_at")
    list_filter = ("role",)
    search_fields = ("email", "phone", "org__name")
    readonly_fields = ("id", "token_hash", "created_at", "updated_at")


# Registered only on the internal deployment (PLATFORM_ADMIN_ENABLED); importable everywhere.
if apps.is_installed("django.contrib.admin"):
    admin.site.register(Organisation, OrganisationAdmin)
    admin.site.register(Membership, MembershipAdmin)
    admin.site.register(Invitation, InvitationAdmin)

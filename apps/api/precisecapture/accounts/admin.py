from django.apps import apps
from django.contrib import admin

from precisecapture.accounts.models import Device, User
from precisecapture.common.admin import PlatformModelAdmin


class UserAdmin(PlatformModelAdmin):
    list_display = ("email", "phone", "name", "status", "is_staff", "last_login_at", "created_at")
    list_filter = ("status", "is_staff")
    search_fields = ("email", "phone", "name")
    readonly_fields = ("id", "password", "created_at", "updated_at", "last_login_at")
    ordering = ("-created_at",)


class DeviceAdmin(PlatformModelAdmin):
    list_display = ("id", "user", "platform", "model", "app_version", "last_sync_at", "revoked_at")
    list_filter = ("platform",)
    search_fields = ("user__email", "user__phone", "model")
    readonly_fields = ("id", "created_at", "updated_at")


# Registered only on the internal deployment (PLATFORM_ADMIN_ENABLED); importable everywhere.
if apps.is_installed("django.contrib.admin"):
    admin.site.register(User, UserAdmin)
    admin.site.register(Device, DeviceAdmin)

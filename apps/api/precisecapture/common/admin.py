"""
Platform admin base class. The Django admin is mounted only when PLATFORM_ADMIN_ENABLED
is true (an internal-only deployment) and reads and writes through the `platform` alias
(pc_platform, BYPASSRLS), never through the tenant-scoped `default` connection.
"""

from typing import Any

from django.contrib import admin
from django.db.models import Model, QuerySet
from django.http import HttpRequest

PLATFORM_ALIAS = "platform"


# ModelAdmin is generic in django-stubs but not subscriptable at runtime.
class PlatformModelAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    using = PLATFORM_ALIAS

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).using(self.using)

    def save_model(self, request: HttpRequest, obj: Model, form: Any, change: bool) -> None:
        obj.save(using=self.using)

    def delete_model(self, request: HttpRequest, obj: Model) -> None:
        obj.delete(using=self.using)

    def formfield_for_foreignkey(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        return super().formfield_for_foreignkey(db_field, request, using=self.using, **kwargs)

    def formfield_for_manytomany(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        return super().formfield_for_manytomany(db_field, request, using=self.using, **kwargs)

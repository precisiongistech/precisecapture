from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from precisecapture.common.tenancy import clear_tenant


class TenantContextResetMiddleware:
    """Ensure no tenant leaks from one request to the next on a reused worker thread."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        clear_tenant()
        try:
            return self.get_response(request)
        finally:
            clear_tenant()

from django.shortcuts import render


def placeholder(request, title: str = "Em construção"):
    """Página provisória usada pelos módulos ainda não implementados."""
    return render(request, "components/placeholder.html", {"title": title})


def permission_denied(request, exception=None):
    message = str(exception) if exception and str(exception) else ""
    return render(request, "errors/403.html", {"message": message}, status=403)


def page_not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def server_error(request):
    return render(request, "errors/500.html", status=500)

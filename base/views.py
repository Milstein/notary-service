import os

from django.shortcuts import render


def handler404(request, exception):
    response = render(request, '404.html', {})
    response.status_code = 404
    return response


def handler500(request):
    response = render(request, '500.html', {})
    response.status_code = 500
    return response


def whoami(request):
    hostname = os.getenv('NS_NAME', 'localhost')
    return render(request, 'whoami.html', {'home_page': 'active', 'hostname': hostname})

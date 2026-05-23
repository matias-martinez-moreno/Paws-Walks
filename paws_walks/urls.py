"""
URL configuration for paws_walks project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

# Django imports
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
# Third-party imports
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # URL para internacionalización, permite cambiar el idioma de la aplicación.
    path("i18n/", include("django.conf.urls.i18n")),
    # Redirige la raíz del sitio a la página de login, lo que mejora la experiencia del usuario al acceder al sitio sin especificar una ruta.
    path("", RedirectView.as_view(url="/login/", permanent=False)),
    # URL para el panel de administración de Django, que permite gestionar los modelos registrados en admin.py.
    path("admin/", admin.site.urls),
    # Incluye las URLs de la aplicación "servicios", que contiene las vistas y rutas específicas de la funcionalidad principal del sitio.
    path("", include("servicios.urls")),
    # URLs para la API REST, organizadas bajo el prefijo "api/" para mantener una estructura clara y separada de las vistas tradicionales.
    path("api/", include(("servicios.api.urls", "servicios_api"), namespace="api")),
    # URLs para la documentación de la API, utilizando drf-spectacular para generar el esquema y la interfaz Swagger.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # URL para la interfaz de documentación Swagger, que permite a los desarrolladores explorar y probar la API de manera interactiva.
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

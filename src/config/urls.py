from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from billing.views import FirstLaunchLoginView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", FirstLaunchLoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("billing.urls")),
]

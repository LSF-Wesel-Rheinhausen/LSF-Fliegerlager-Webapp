from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

from billing.forms import EmailOrUsernameAuthenticationForm
from billing.views import FirstLaunchLoginView
from config.views import page_not_found

handler404 = "config.views.page_not_found"

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        FirstLaunchLoginView.as_view(
            authentication_form=EmailOrUsernameAuthenticationForm,
            template_name="registration/login.html",
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("billing.urls")),
    re_path(r"^.*$", page_not_found, name="page-not-found"),
]

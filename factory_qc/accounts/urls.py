from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html",
                                                redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),  # POST only (Django 5)
    path("after-login/", views.PostLoginRedirectView.as_view(), name="post_login"),
    path("no-role/", views.NoRoleView.as_view(), name="no_role"),
    path("dashboard/engineer/", views.EngineerDashboardView.as_view(), name="engineer_dashboard"),
    path("dashboard/inspector/", views.InspectorDashboardView.as_view(), name="inspector_dashboard"),
    path("dashboard/supervisor/", views.SupervisorDashboardView.as_view(), name="supervisor_dashboard"),
    path("dashboard/plant-manager/", views.PlantManagerDashboardView.as_view(), name="plant_manager_dashboard"),
]

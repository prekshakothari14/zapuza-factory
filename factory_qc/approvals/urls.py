from django.urls import path
from . import views

app_name = "approvals"

urlpatterns = [
    # Supervisor review queue
    path("queue/", views.ApprovalQueueView.as_view(), name="queue"),
    # Quarantine holding area
    path("quarantine/", views.QuarantineListView.as_view(), name="quarantine_list"),
    # Detail view (read-only for supervisor)
    path("<int:pk>/", views.ApprovalDetailView.as_view(), name="detail"),
    # Action endpoints (POST only)
    path("<int:pk>/approve/", views.ApproveView.as_view(), name="approve"),
    path("<int:pk>/quarantine/", views.QuarantineView.as_view(), name="quarantine"),
    path("<int:pk>/concession/", views.ConcessionView.as_view(), name="concession"),
]

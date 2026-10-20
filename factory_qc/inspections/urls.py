from django.urls import path
from . import views

app_name = "inspections"

urlpatterns = [
    # Quality Engineer template URLs
    path("templates/", views.TemplateListView.as_view(), name="template_list"),
    path("templates/new/", views.TemplateCreateView.as_view(), name="template_create"),
    path("templates/<int:pk>/", views.TemplateDetailView.as_view(), name="template_detail"),
    path("templates/<int:pk>/edit/", views.TemplateUpdateView.as_view(), name="template_edit"),
    path("templates/<int:pk>/approve/", views.TemplateApproveView.as_view(), name="template_approve"),

    # Inspector URLs
    path("new/", views.InspectionCreateView.as_view(), name="inspection_create"),
    path("checklists/", views.ChecklistListView.as_view(), name="checklist_list"),
    path("checklists/<int:pk>/", views.ChecklistDetailView.as_view(), name="checklist_detail"),
]

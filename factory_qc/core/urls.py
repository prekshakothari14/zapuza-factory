from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("factories/", views.FactoryListView.as_view(), name="factory_list"),
    path("factories/new/", views.FactoryCreateView.as_view(), name="factory_create"),
    path("factories/<int:pk>/edit/", views.FactoryUpdateView.as_view(), name="factory_edit"),
    path("machines/", views.MachineListView.as_view(), name="machine_list"),
    path("machines/new/", views.MachineCreateView.as_view(), name="machine_create"),
    path("machines/<int:pk>/edit/", views.MachineUpdateView.as_view(), name="machine_edit"),
    path("parts/", views.PartListView.as_view(), name="part_list"),
    path("parts/new/", views.PartCreateView.as_view(), name="part_create"),
    path("parts/<int:pk>/edit/", views.PartUpdateView.as_view(), name="part_edit"),
    path("gauges/", views.GaugeListView.as_view(), name="gauge_list"),
    path("gauges/new/", views.GaugeCreateView.as_view(), name="gauge_create"),
    path("gauges/<int:pk>/edit/", views.GaugeUpdateView.as_view(), name="gauge_edit"),
]

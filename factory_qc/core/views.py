from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from accounts.mixins import MasterDataAccessMixin

from .forms import FactoryForm, GaugeForm, MachineForm, PartNumberForm
from .models import Factory, Gauge, Machine, PartNumber


class MasterListView(MasterDataAccessMixin, ListView):
    """Generic list page (Quality Engineer / Admin only); subclasses set model, title, columns."""
    template_name = "core/list.html"
    title = ""
    create_url_name = ""
    edit_url_name = ""
    columns = []  # list of (header, attribute) pairs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title=self.title, create_url_name=self.create_url_name,
                   edit_url_name=self.edit_url_name, headers=[c[0] for c in self.columns])
        # Pre-build rows so the template stays simple.
        ctx["rows"] = [
            {"pk": obj.pk, "obj": obj, "cells": [getattr(obj, c[1]) for c in self.columns]}
            for obj in ctx["object_list"]
        ]
        return ctx


class MasterFormMixin(MasterDataAccessMixin):
    """Create/edit pages share the same access rule (Quality Engineer / Admin only)."""
    template_name = "core/form.html"
    title = ""
    success_url = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title
        ctx["cancel_url"] = self.success_url
        return ctx



# ---- Factory ----
class FactoryListView(MasterListView):
    model = Factory
    title = "Factories"
    create_url_name = "core:factory_create"
    edit_url_name = "core:factory_edit"
    columns = [("Name", "name"), ("Location", "location")]


class FactoryCreateView(MasterFormMixin, CreateView):
    model = Factory
    form_class = FactoryForm
    title = "Add Factory"
    success_url = reverse_lazy("core:factory_list")


class FactoryUpdateView(MasterFormMixin, UpdateView):
    model = Factory
    form_class = FactoryForm
    title = "Edit Factory"
    success_url = reverse_lazy("core:factory_list")


# ---- Machine ----
class MachineListView(MasterListView):
    model = Machine
    title = "Machines"
    create_url_name = "core:machine_create"
    edit_url_name = "core:machine_edit"
    columns = [("Name", "name"), ("Factory", "factory"), ("Active", "is_active")]


class MachineCreateView(MasterFormMixin, CreateView):
    model = Machine
    form_class = MachineForm
    title = "Add Machine"
    success_url = reverse_lazy("core:machine_list")


class MachineUpdateView(MasterFormMixin, UpdateView):
    model = Machine
    form_class = MachineForm
    title = "Edit Machine"
    success_url = reverse_lazy("core:machine_list")


# ---- Part number ----
class PartListView(MasterListView):
    model = PartNumber
    title = "Part Numbers"
    create_url_name = "core:part_create"
    edit_url_name = "core:part_edit"
    columns = [("Part No", "part_no"), ("Description", "description")]


class PartCreateView(MasterFormMixin, CreateView):
    model = PartNumber
    form_class = PartNumberForm
    title = "Add Part"
    success_url = reverse_lazy("core:part_list")


class PartUpdateView(MasterFormMixin, UpdateView):
    model = PartNumber
    form_class = PartNumberForm
    title = "Edit Part"
    success_url = reverse_lazy("core:part_list")


# ---- Gauge ----
class GaugeListView(MasterListView):
    model = Gauge
    template_name = "core/gauge_list.html"
    title = "Gauges"
    create_url_name = "core:gauge_create"
    edit_url_name = "core:gauge_edit"
    columns = [("Serial No", "serial_no"), ("Type", "gauge_type"),
               ("Calibration Expiry", "calibration_expiry"), ("Days Left", "days_left")]


class GaugeCreateView(MasterFormMixin, CreateView):
    model = Gauge
    form_class = GaugeForm
    title = "Add Gauge"
    success_url = reverse_lazy("core:gauge_list")


class GaugeUpdateView(MasterFormMixin, UpdateView):
    model = Gauge
    form_class = GaugeForm
    title = "Edit Gauge"
    success_url = reverse_lazy("core:gauge_list")

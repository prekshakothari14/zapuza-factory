from django import forms

from .models import Factory, Gauge, Machine, PartNumber


class BootstrapFormMixin:
    """Adds Bootstrap 5 classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class FactoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Factory
        fields = ["name", "location"]


class MachineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Machine
        fields = ["name", "factory", "is_active"]


class PartNumberForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PartNumber
        fields = ["part_no", "description"]


class GaugeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Gauge
        fields = ["serial_no", "gauge_type", "calibration_expiry"]
        widgets = {"calibration_expiry": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

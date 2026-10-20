from django import forms
from django.forms import inlineformset_factory

from core.forms import BootstrapFormMixin
from core.models import Gauge, Machine
from .models import Checklist, DefectPhoto, InspectionTemplate, Measurement, TemplateField


class GaugeModelChoiceField(forms.ModelChoiceField):
    """Marks expired gauges with (EXPIRED) in dropdown labels."""

    def label_from_instance(self, obj):
        if not obj.is_calibration_valid:
            return f"{obj.serial_no} ({obj.gauge_type}) (EXPIRED)"
        return f"{obj.serial_no} ({obj.gauge_type})"


class InspectionTemplateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InspectionTemplate
        fields = ["name", "part", "revision", "is_active"]


class TemplateFieldForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = TemplateField
        fields = [
            "order",
            "name",
            "field_type",
            "nominal",
            "upper_tol",
            "lower_tol",
            "max_value",
            "unit",
            "is_ctq",
        ]
        widgets = {
            "order": forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width: 70px;"}),
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Characteristic name"}),
            "field_type": forms.Select(attrs={"class": "form-select form-select-sm field-type-select"}),
            "nominal": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001"}),
            "upper_tol": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001", "placeholder": "+0.050"}),
            "lower_tol": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001", "placeholder": "-0.020"}),
            "max_value": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001", "placeholder": "0.800"}),
            "unit": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "mm"}),
            "is_ctq": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


TemplateFieldFormSet = inlineformset_factory(
    InspectionTemplate,
    TemplateField,
    form=TemplateFieldForm,
    extra=1,
    can_delete=True,
)


class InspectionStartForm(BootstrapFormMixin, forms.Form):
    """Form to choose an approved template, machine, and job number."""

    template = forms.ModelChoiceField(
        queryset=InspectionTemplate.objects.filter(status=InspectionTemplate.Status.APPROVED, is_active=True),
        empty_label="-- Select Approved Template --",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    machine = forms.ModelChoiceField(
        queryset=Machine.objects.filter(is_active=True),
        empty_label="-- Select Machine --",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    job_no = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. JOB-1001"}),
    )


class MeasurementForm(BootstrapFormMixin, forms.ModelForm):
    gauge = GaugeModelChoiceField(
        queryset=Gauge.objects.all(),
        required=False,
        empty_label="-- Select Gauge --",
    )

    class Meta:
        model = Measurement
        fields = ["field", "value", "visual_ok", "gauge", "remarks"]

    def clean_gauge(self):
        gauge = self.cleaned_data.get("gauge")
        if gauge and not gauge.is_calibration_valid:
            raise forms.ValidationError("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.")
        return gauge

    def clean(self):
        cleaned_data = super().clean()
        gauge = cleaned_data.get("gauge")
        if gauge and not gauge.is_calibration_valid:
            raise forms.ValidationError("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.")
        return cleaned_data


class BaseMeasurementFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            gauge = form.cleaned_data.get("gauge")
            if gauge and not gauge.is_calibration_valid:
                raise forms.ValidationError("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.")


MeasurementFormSet = inlineformset_factory(
    Checklist,
    Measurement,
    form=MeasurementForm,
    formset=BaseMeasurementFormSet,
    extra=0,
)


class DefectPhotoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DefectPhoto
        fields = ["image"]


# ---- Defect photo validation (used by inspection submit view) ----

ALLOWED_PHOTO_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}
ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def validate_defect_photo_file(uploaded_file):
    """
    Validate a single defect photo upload.
    Returns an error string, or None if valid.
    Accepts jpg/png/webp only, max 5 MB.
    """
    if uploaded_file is None:
        return "No file provided."

    name = (getattr(uploaded_file, "name", "") or "").lower()
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    size = getattr(uploaded_file, "size", 0) or 0

    ext_ok = any(name.endswith(ext) for ext in ALLOWED_PHOTO_EXTENSIONS)
    type_ok = content_type in ALLOWED_PHOTO_CONTENT_TYPES or content_type == ""

    if not ext_ok and not type_ok:
        return (
            f"File '{getattr(uploaded_file, 'name', 'unknown')}' has an invalid type. "
            "Only JPG, PNG, and WebP images are allowed."
        )
    if not ext_ok:
        return (
            f"File '{getattr(uploaded_file, 'name', 'unknown')}' has an invalid extension. "
            "Only JPG, PNG, and WebP images are allowed."
        )
    if size > MAX_PHOTO_SIZE_BYTES:
        return (
            f"File '{getattr(uploaded_file, 'name', 'unknown')}' is too large "
            f"({size / (1024 * 1024):.1f} MB). Maximum size is 5 MB."
        )
    # Verify it is a real image with Pillow
    try:
        from PIL import Image
        pos = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as img:
            img.verify()
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0 if pos is None else 0)
    except Exception:
        return (
            f"File '{getattr(uploaded_file, 'name', 'unknown')}' is not a valid image. "
            "Only real JPG, PNG, or WebP files are accepted."
        )
    return None


def validate_defect_photos_for_field(field_name, is_pass, photo_files):
    """
    Server-side rule: failed fields need at least 2 valid photos.
    Returns a list of error messages (may be empty).
    """
    errors = []
    photo_files = list(photo_files or [])

    for f in photo_files:
        err = validate_defect_photo_file(f)
        if err:
            errors.append(err)

    if not is_pass:
        count = len(photo_files)
        if count < 2:
            errors.append(
                f"Upload at least 2 photos for '{field_name}' ({count} uploaded)"
            )
    return errors

import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from accounts import roles
from accounts.mixins import MasterDataAccessMixin
from core.models import Gauge, Machine
from .forms import InspectionTemplateForm, TemplateFieldFormSet, validate_defect_photos_for_field
from .models import Checklist, DefectPhoto, InspectionTemplate, Measurement, TemplateField


# ==============================================================================
# Quality Engineer Views
# ==============================================================================

class TemplateListView(MasterDataAccessMixin, ListView):
    model = InspectionTemplate
    template_name = "inspections/template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        return InspectionTemplate.objects.select_related("part").prefetch_related("fields").order_by("-created_at")


class TemplateCreateView(MasterDataAccessMixin, View):
    template_name = "inspections/template_form.html"

    def get(self, request):
        form = InspectionTemplateForm()
        formset = TemplateFieldFormSet()
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "title": "Create Inspection Template",
                "is_create": True,
            },
        )

    def post(self, request):
        form = InspectionTemplateForm(request.POST)
        formset = TemplateFieldFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                template = form.save(commit=False)
                template.status = InspectionTemplate.Status.DRAFT
                template.save()
                formset.instance = template
                formset.save()

            messages.success(request, f"Template '{template.name}' ({template.revision}) created in Draft.")
            return redirect("inspections:template_detail", pk=template.pk)

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "title": "Create Inspection Template",
                "is_create": True,
            },
        )


class TemplateUpdateView(MasterDataAccessMixin, View):
    template_name = "inspections/template_form.html"

    def get(self, request, pk):
        template = get_object_or_404(InspectionTemplate, pk=pk)
        if template.is_approved:
            messages.warning(request, "Approved templates cannot be edited.")
            return redirect("inspections:template_detail", pk=template.pk)

        form = InspectionTemplateForm(instance=template)
        formset = TemplateFieldFormSet(instance=template)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "template_obj": template,
                "title": f"Edit Template: {template.name} ({template.revision})",
                "is_create": False,
            },
        )

    def post(self, request, pk):
        template = get_object_or_404(InspectionTemplate, pk=pk)
        if template.is_approved:
            messages.error(request, "Approved templates cannot be edited.")
            return redirect("inspections:template_detail", pk=template.pk)

        form = InspectionTemplateForm(request.POST, instance=template)
        formset = TemplateFieldFormSet(request.POST, instance=template)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                template = form.save()
                formset.save()

            messages.success(request, f"Template '{template.name}' ({template.revision}) updated.")
            return redirect("inspections:template_detail", pk=template.pk)

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "template_obj": template,
                "title": f"Edit Template: {template.name} ({template.revision})",
                "is_create": False,
            },
        )


class TemplateDetailView(MasterDataAccessMixin, DetailView):
    model = InspectionTemplate
    template_name = "inspections/template_detail.html"
    context_object_name = "template_obj"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["fields"] = self.object.fields.all().order_by("order", "id")
        return ctx


class TemplateApproveView(MasterDataAccessMixin, View):
    """Approve a draft template, locking it permanently."""

    def post(self, request, pk):
        template = get_object_or_404(InspectionTemplate, pk=pk)
        if template.is_approved:
            messages.info(request, "Template is already approved.")
            return redirect("inspections:template_detail", pk=template.pk)

        if not template.fields.exists():
            messages.error(request, "Cannot approve a template with no fields. Please add at least one field first.")
            return redirect("inspections:template_detail", pk=template.pk)

        template.status = InspectionTemplate.Status.APPROVED
        template.save()
        messages.success(request, f"Template '{template.name}' ({template.revision}) has been APPROVED and is now locked.")
        return redirect("inspections:template_detail", pk=template.pk)


# ==============================================================================
# Inspector Views
# ==============================================================================

class InspectionCreateView(LoginRequiredMixin, View):
    """
    Inspector page:
    Choose an approved template, a machine and a job no, then see ALL fields on one page
    (name, expected range, value input or Yes/No, gauge dropdown).
    JS turns the input GREEN or RED as the user types; CTQ fields show an ORANGE badge.
    The server re-validates and saves is_within_tolerance.
    Submission is blocked if any field is empty.
    Only Inspectors (and superusers) may open or submit this view.
    """
    template_name = "inspections/inspection_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        role = roles.get_role(request.user)
        if not (request.user.is_superuser or role == roles.INSPECTOR):
            raise PermissionDenied("Only Inspectors may record inspections.")
        return super().dispatch(request, *args, **kwargs)

    def get_template_catalog(self):
        """Prepare JSON-serializable catalog of approved templates and their fields."""
        approved_templates = InspectionTemplate.objects.filter(
            status=InspectionTemplate.Status.APPROVED,
            is_active=True,
        ).prefetch_related("fields").select_related("part")

        catalog = {}
        for t in approved_templates:
            fields_list = []
            for f in t.fields.all().order_by("order", "id"):
                fields_list.append({
                    "id": f.id,
                    "order": f.order,
                    "name": f.name,
                    "field_type": f.field_type,
                    "nominal": str(f.nominal) if f.nominal is not None else None,
                    "upper_tol": str(f.upper_tol) if f.upper_tol is not None else None,
                    "lower_tol": str(f.lower_tol) if f.lower_tol is not None else None,
                    "max_value": str(f.max_value) if f.max_value is not None else None,
                    "unit": f.unit,
                    "is_ctq": f.is_ctq,
                    "expected_range": f.expected_range,
                })
            catalog[t.id] = {
                "id": t.id,
                "name": t.name,
                "revision": t.revision,
                "part_no": t.part.part_no,
                "part_desc": t.part.description,
                "fields": fields_list,
            }
        return catalog

    def get(self, request):
        approved_templates = InspectionTemplate.objects.filter(
            status=InspectionTemplate.Status.APPROVED,
            is_active=True,
        ).select_related("part")
        machines = Machine.objects.filter(is_active=True).select_related("factory")
        gauges = Gauge.objects.all().order_by("serial_no")

        selected_template_id = request.GET.get("template")
        selected_template = None
        if selected_template_id:
            try:
                selected_template = approved_templates.get(pk=int(selected_template_id))
            except (ValueError, InspectionTemplate.DoesNotExist):
                selected_template = None

        template_catalog = self.get_template_catalog()

        return render(
            request,
            self.template_name,
            {
                "templates": approved_templates,
                "machines": machines,
                "gauges": gauges,
                "selected_template": selected_template,
                "selected_template_id": selected_template.id if selected_template else "",
                "template_catalog_json": json.dumps(template_catalog),
            },
        )

    def post(self, request):
        template_id = request.POST.get("template")
        machine_id = request.POST.get("machine")
        job_no = request.POST.get("job_no", "").strip()

        approved_templates = InspectionTemplate.objects.filter(
            status=InspectionTemplate.Status.APPROVED,
            is_active=True,
        ).select_related("part")
        machines = Machine.objects.filter(is_active=True).select_related("factory")
        gauges = Gauge.objects.all().order_by("serial_no")
        template_catalog = self.get_template_catalog()

        errors = []

        if not template_id:
            errors.append("Please select an approved inspection template.")
        if not machine_id:
            errors.append("Please select a machine.")
        if not job_no:
            errors.append("Job number cannot be empty.")

        template = None
        if template_id:
            try:
                template = approved_templates.get(pk=int(template_id))
            except (ValueError, InspectionTemplate.DoesNotExist):
                errors.append("The selected template is invalid or not approved.")

        machine = None
        if machine_id:
            try:
                machine = machines.get(pk=int(machine_id))
            except (ValueError, Machine.DoesNotExist):
                errors.append("The selected machine is invalid or inactive.")

        # If header validation passed, validate every single field
        field_data = []
        if template:
            fields = template.fields.all().order_by("order", "id")
            if not fields.exists():
                errors.append("This template has no inspection fields.")

            for f in fields:
                field_val_raw = request.POST.get(f"field_{f.id}_value", "").strip()
                visual_ok_raw = request.POST.get(f"field_{f.id}_visual_ok", "").strip()
                gauge_id_raw = request.POST.get(f"field_{f.id}_gauge", "").strip()
                remarks_raw = request.POST.get(f"field_{f.id}_remarks", "").strip()

                gauge_obj = None
                needs_gauge = f.field_type in (
                    TemplateField.FieldType.DIMENSION,
                    TemplateField.FieldType.MAX_THRESHOLD,
                )
                if gauge_id_raw:
                    try:
                        gauge_obj = gauges.get(pk=int(gauge_id_raw))
                        if not gauge_obj.is_calibration_valid:
                            errors.append("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.")
                    except (ValueError, Gauge.DoesNotExist):
                        gauge_obj = None
                        if needs_gauge:
                            errors.append(f"Select the gauge used for '{f.name}'")
                elif needs_gauge:
                    errors.append(f"Select the gauge used for '{f.name}'")

                # Collect defect photos for this field
                field_photos = request.FILES.getlist(f"field_{f.id}_photos")
                for key in request.FILES:
                    if key.startswith(f"field_{f.id}_photo_") and key != f"field_{f.id}_photos":
                        field_photos.extend(request.FILES.getlist(key))

                # Submission is blocked if any field is empty
                if f.field_type in (TemplateField.FieldType.DIMENSION, TemplateField.FieldType.MAX_THRESHOLD):
                    if not field_val_raw:
                        errors.append(f"Field '{f.name}' cannot be empty. Please enter a measured value.")
                    else:
                        try:
                            val_dec = Decimal(field_val_raw)
                        except Exception:
                            errors.append(f"Invalid numeric value '{field_val_raw}' for field '{f.name}'.")
                            continue
                        # At most 3 decimal places, max_digits=10
                        try:
                            as_tuple = val_dec.as_tuple()
                            decimals = -as_tuple.exponent if as_tuple.exponent < 0 else 0
                            digits = len(as_tuple.digits)
                            if decimals > 3:
                                errors.append(f"Enter at most 3 decimal places for '{f.name}'")
                                continue
                            if digits > 10:
                                errors.append(f"Value for '{f.name}' is too large (max 10 digits).")
                                continue
                            # quantize to 3 places for storage consistency
                            val_dec = val_dec.quantize(Decimal("0.001"))
                        except Exception:
                            errors.append(f"Invalid numeric value '{field_val_raw}' for field '{f.name}'.")
                            continue
                        is_pass = f.evaluate(value=val_dec)
                        errors.extend(
                            validate_defect_photos_for_field(f.name, is_pass, field_photos)
                        )
                        field_data.append({
                            "field": f,
                            "value": val_dec,
                            "visual_ok": None,
                            "gauge": gauge_obj,
                            "is_within_tolerance": is_pass,
                            "remarks": remarks_raw,
                            "photos": field_photos,
                        })

                elif f.field_type == TemplateField.FieldType.VISUAL:
                    if not visual_ok_raw:
                        errors.append(f"Visual check '{f.name}' cannot be empty. Please select Yes or No.")
                    else:
                        vis_bool = visual_ok_raw.lower() in ("yes", "true", "1")
                        is_pass = f.evaluate(visual_ok=vis_bool)

                        errors.extend(
                            validate_defect_photos_for_field(f.name, is_pass, field_photos)
                        )

                        field_data.append({
                            "field": f,
                            "value": None,
                            "visual_ok": vis_bool,
                            "gauge": gauge_obj,
                            "is_within_tolerance": is_pass,
                            "remarks": remarks_raw,
                            "photos": field_photos,
                        })

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(
                request,
                self.template_name,
                {
                    "templates": approved_templates,
                    "machines": machines,
                    "gauges": gauges,
                    "selected_template": template,
                    "selected_template_id": int(template_id) if template_id and template_id.isdigit() else "",
                    "selected_machine_id": int(machine_id) if machine_id and machine_id.isdigit() else "",
                    "submitted_job_no": job_no,
                    "submitted_data": request.POST,
                    "template_catalog_json": json.dumps(template_catalog),
                },
            )

        # Determine checklist status:
        # If a CTQ field fails, set checklist status CTQ_FAILED (frozen) and send an alert email to the Quality Head.
        # Otherwise, on submit set status PENDING_REVIEW.
        has_ctq_failure = any(item["field"].is_ctq and not item["is_within_tolerance"] for item in field_data)
        checklist_status = Checklist.Status.CTQ_FAILED if has_ctq_failure else Checklist.Status.PENDING_REVIEW

        # All validation passed: atomically save Checklist, Measurements, and DefectPhotos
        try:
            with transaction.atomic():
                checklist = Checklist.objects.create(
                    template=template,
                    machine=machine,
                    job_no=job_no,
                    inspector=request.user,
                    status=checklist_status,
                    submitted_at=timezone.now(),
                )
                for item in field_data:
                    m = Measurement.objects.create(
                        checklist=checklist,
                        field=item["field"],
                        value=item["value"],
                        visual_ok=item["visual_ok"],
                        gauge=item["gauge"],
                        is_within_tolerance=item["is_within_tolerance"],
                        remarks=item["remarks"],
                    )
                    for photo_file in item["photos"]:
                        DefectPhoto.objects.create(measurement=m, image=photo_file)
        except DjangoValidationError as exc:
            msgs = []
            if hasattr(exc, "message_dict"):
                for v in exc.message_dict.values():
                    msgs.extend(v if isinstance(v, (list, tuple)) else [v])
            elif hasattr(exc, "messages"):
                msgs = list(exc.messages)
            else:
                msgs = [str(exc)]
            for m in msgs:
                messages.error(request, m)
            return render(
                request,
                self.template_name,
                {
                    "templates": approved_templates,
                    "machines": machines,
                    "gauges": gauges,
                    "template_catalog_json": json.dumps(template_catalog),
                    "selected_template_id": template_id or "",
                    "selected_machine_id": machine_id or "",
                    "selected_job_no": job_no,
                },
            )

        if has_ctq_failure:
            failed_ctqs = [item for item in field_data if item["field"].is_ctq and not item["is_within_tolerance"]]
            subject = f"[URGENT] CTQ Inspection Failure - Job {job_no} ({template.name})"
            body = (
                f"CRITICAL QUALITY ALERT: CTQ Characteristic Failure Detected\n\n"
                f"Job Number: {job_no}\n"
                f"Part: {template.part.part_no} - {template.part.description}\n"
                f"Template: {template.name} ({template.revision})\n"
                f"Machine: {machine.name} ({machine.factory.name})\n"
                f"Inspector: {request.user.username}\n"
                f"Timestamp: {checklist.submitted_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Failed CTQ Characteristics:\n"
            )
            for item in failed_ctqs:
                val_disp = item["value"] if item["value"] is not None else ("Yes" if item["visual_ok"] else "No")
                body += f" - {item['field'].name}: Measured={val_disp}, Expected={item['field'].expected_range}\n"
            body += f"\nChecklist #{checklist.pk} status is frozen to CTQ_FAILED.\n"

            try:
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "qc-system@factoryqc.local"),
                    recipient_list=[getattr(settings, "QUALITY_HEAD_EMAIL", "qualityhead@factoryqc.local")],
                    fail_silently=False,
                )
            except Exception:
                pass

            messages.error(
                request,
                f"CRITICAL: Inspection for Job '{job_no}' failed on CTQ characteristics! Checklist status is frozen to CTQ_FAILED. Quality Head alerted.",
            )
        else:
            messages.success(
                request,
                f"Inspection for Job '{job_no}' submitted successfully with status PENDING_REVIEW.",
            )

        return redirect("inspections:checklist_detail", pk=checklist.pk)


class ChecklistListView(LoginRequiredMixin, ListView):
    model = Checklist
    template_name = "inspections/checklist_list.html"
    context_object_name = "checklists"

    def get_queryset(self):
        qs = Checklist.objects.select_related("template", "template__part", "machine", "inspector").prefetch_related("measurements", "measurements__field")
        user = self.request.user
        if user.is_superuser:
            return qs.order_by("-created_at")
        role = roles.get_role(user)
        if role in (roles.QUALITY_ENGINEER, roles.SUPERVISOR, roles.PLANT_MANAGER):
            return qs.order_by("-created_at")
        # Inspector (and anyone else): only own checklists
        return qs.filter(inspector=user).order_by("-created_at")


class ChecklistDetailView(LoginRequiredMixin, DetailView):
    model = Checklist
    template_name = "inspections/checklist_detail.html"
    context_object_name = "checklist"

    def get_queryset(self):
        qs = Checklist.objects.select_related("template", "template__part", "machine", "inspector")
        user = self.request.user
        if user.is_superuser:
            return qs
        role = roles.get_role(user)
        if role in (roles.QUALITY_ENGINEER, roles.SUPERVISOR, roles.PLANT_MANAGER):
            return qs
        # Inspector: only own checklists
        return qs.filter(inspector=user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["measurements"] = self.object.measurements.select_related("field", "gauge").prefetch_related("photos").order_by("field__order", "field__id")
        ctx["is_readonly"] = True  # After submit, the checklist is read-only for the inspector
        return ctx

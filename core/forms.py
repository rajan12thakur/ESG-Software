from django import forms

from core.models import CompanyProfile, Department, Facility, OrganizationUnit


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ["sector", "sub_sector", "employee_count", "annual_revenue", "listed_status", "stock_exchange", "description"]
        widgets = {
            "sector": forms.TextInput(attrs={"placeholder": "Enter sector"}),
            "sub_sector": forms.TextInput(attrs={"placeholder": "Enter sub-sector"}),
            "employee_count": forms.NumberInput(attrs={"placeholder": "Enter employee count"}),
            "annual_revenue": forms.NumberInput(attrs={"step": "0.01", "placeholder": "Enter annual revenue"}),
            "listed_status": forms.TextInput(attrs={"placeholder": "Enter listed status"}),
            "stock_exchange": forms.TextInput(attrs={"placeholder": "Enter stock exchange"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Enter company description"}),
        }


class OrganizationUnitForm(forms.ModelForm):
    class Meta:
        model = OrganizationUnit
        fields = ["parent_unit", "name", "unit_type", "country", "state", "city", "ownership_percentage", "operational_control", "financial_control", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Enter organization unit name"}),
            "unit_type": forms.TextInput(attrs={"placeholder": "Enter unit type"}),
            "country": forms.TextInput(attrs={"placeholder": "Enter country"}),
            "state": forms.TextInput(attrs={"placeholder": "Enter state"}),
            "city": forms.TextInput(attrs={"placeholder": "Enter city"}),
            "ownership_percentage": forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100", "placeholder": "Enter ownership percentage"}),
        }

    def __init__(self, *args, company, parent_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = parent_queryset
        if queryset is None:
            queryset = OrganizationUnit.objects.filter(company=company)
        self.fields["parent_unit"].queryset = queryset.exclude(pk=self.instance.pk)


class FacilityForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = ["organization_unit", "name", "facility_type", "address", "country", "state", "city", "latitude", "longitude", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Enter facility name"}),
            "facility_type": forms.TextInput(attrs={"placeholder": "Enter facility type"}),
            "address": forms.Textarea(attrs={"rows": 3, "placeholder": "Enter address"}),
            "country": forms.TextInput(attrs={"placeholder": "Enter country"}),
            "state": forms.TextInput(attrs={"placeholder": "Enter state"}),
            "city": forms.TextInput(attrs={"placeholder": "Enter city"}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001", "placeholder": "Enter latitude"}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001", "placeholder": "Enter longitude"}),
        }

    def __init__(self, *args, company, organization_unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization_unit:
            # A facility is always created in the context of an organization unit.
            self.fields.pop("organization_unit")
        else:
            self.fields["organization_unit"].queryset = OrganizationUnit.objects.filter(company=company, is_active=True)


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Enter department name"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Enter department description"}),
        }

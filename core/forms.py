from django import forms

from core.models import CompanyProfile, Department, Facility, OrganizationUnit


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ["sector", "sub_sector", "employee_count", "annual_revenue", "listed_status", "stock_exchange", "description"]


class OrganizationUnitForm(forms.ModelForm):
    class Meta:
        model = OrganizationUnit
        fields = ["parent_unit", "name", "unit_type", "country", "state", "city", "ownership_percentage", "operational_control", "financial_control", "is_active"]

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

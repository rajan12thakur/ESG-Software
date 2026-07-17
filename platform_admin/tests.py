from django import forms
from django.test import TestCase

from platform_admin.forms import CompanyForm, FirstCompanyAdminForm


class PlatformAdminFormWidgetTests(TestCase):
    def test_company_form_uses_expected_placeholders_and_select_widgets(self):
        form = CompanyForm()

        self.assertEqual(form.fields["legal_name"].widget.attrs["placeholder"], "Enter legal company name")
        self.assertEqual(form.fields["display_name"].widget.attrs["placeholder"], "Enter display name")
        self.assertEqual(form.fields["tenant_code"].widget.attrs["placeholder"], "Enter tenant code")
        self.assertIsInstance(form.fields["currency"].widget, forms.Select)
        self.assertIn(("INR", "INR"), form.fields["currency"].widget.choices)
        self.assertIsInstance(form.fields["timezone"].widget, forms.Select)
        self.assertIn(("Asia/Kolkata", "Asia/Kolkata"), form.fields["timezone"].widget.choices)

    def test_first_company_admin_form_uses_expected_widgets(self):
        form = FirstCompanyAdminForm()

        self.assertIsInstance(form.fields["email"].widget, forms.EmailInput)
        self.assertIsInstance(form.fields["phone"].widget, forms.TelInput)
        self.assertIsInstance(form.fields["password"].widget, forms.PasswordInput)
        self.assertFalse(form.fields["password"].widget.render_value)
        self.assertEqual(form.fields["password"].widget.attrs["placeholder"], "Enter password")

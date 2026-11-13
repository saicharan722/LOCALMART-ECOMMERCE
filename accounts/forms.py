from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction

from ecommerce.input_validation import validate_http_url, validate_mobile_number, validate_person_name
from .models import AdminProfile


class AdminProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(max_length=254)

    class Meta:
        model = AdminProfile
        fields = ("mobile_number", "image_url")
        widgets = {
            "mobile_number": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
            "image_url": forms.URLInput(attrs={"autocomplete": "url", "placeholder": "https://example.com/profile.jpg"}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["email"].initial = user.email
        self.fields["mobile_number"].widget.attrs.update({
            "type": "tel",
            "inputmode": "numeric",
            "pattern": "[6-9][0-9]{9}",
            "maxlength": "10",
            "title": "Enter a 10-digit mobile number using digits only.",
        })

    def clean_first_name(self):
        return validate_person_name(
            self.cleaned_data["first_name"],
            label="First name",
            required=False,
        )

    def clean_last_name(self):
        return validate_person_name(
            self.cleaned_data["last_name"],
            label="Last name",
            required=False,
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    def clean_mobile_number(self):
        return validate_mobile_number(
            self.cleaned_data["mobile_number"],
            required=False,
        )

    def clean_image_url(self):
        return validate_http_url(self.cleaned_data["image_url"])

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.user = self.user
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"]
        if commit:
            self.user.save(update_fields=["first_name", "last_name", "email"])
            profile.save()
        return profile
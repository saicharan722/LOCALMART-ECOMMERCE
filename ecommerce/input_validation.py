import re
import unicodedata
from decimal import Decimal, InvalidOperation

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email


_MOBILE_PATTERN = re.compile(r"[6-9][0-9]{9}\Z")
_POSTAL_CODE_PATTERN = re.compile(r"[1-9][0-9]{5}\Z")
_AMOUNT_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?\Z")
_INTEGER_PATTERN = re.compile(r"[0-9]+\Z")
_SKU_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}\Z")
_VEHICLE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 /-]{2,31}\Z")
_LICENSE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 /-]{3,49}\Z")


def validate_person_name(value, *, label="Name", min_length=2, max_length=150, required=True):
    if not isinstance(value, str):
        raise ValidationError(f"Enter a valid {label.lower()}.")
    value = value.strip()
    if not value and not required:
        return ""
    if not min_length <= len(value) <= max_length:
        raise ValidationError(f"{label} must be between {min_length} and {max_length} characters.")
    if not any(character.isalpha() for character in value):
        raise ValidationError(f"{label} must contain letters.")
    if any(
        not (
            character.isalpha()
            or unicodedata.category(character).startswith("M")
            or character in " .'-’"
        )
        for character in value
    ):
        raise ValidationError(f"{label} may contain letters, spaces, apostrophes, periods, and hyphens.")
    return value


def validate_business_name(value, *, label="Name", max_length=180, required=True):
    if not isinstance(value, str):
        raise ValidationError(f"Enter a valid {label.lower()}.")
    value = value.strip()
    if not value and not required:
        return ""
    if not 2 <= len(value) <= max_length:
        raise ValidationError(f"{label} must be between 2 and {max_length} characters.")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValidationError(f"{label} cannot contain control characters.")
    return value


def validate_mobile_number(value, *, required=True):
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    value = value.strip()
    if not value and not required:
        return ""
    if not _MOBILE_PATTERN.fullmatch(value):
        raise ValidationError("Enter a valid 10-digit mobile number using digits only.")
    return value


def validate_postal_code(value):
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    value = value.strip()
    if not _POSTAL_CODE_PATTERN.fullmatch(value):
        raise ValidationError("Enter a valid 6-digit PIN code using digits only.")
    return value


def validate_address(value, *, label="Address", max_length=1000, required=True):
    if not isinstance(value, str):
        raise ValidationError(f"Enter a valid {label.lower()}.")
    value = value.strip()
    if not value and not required:
        return ""
    if not 5 <= len(value) <= max_length:
        raise ValidationError(f"{label} must be between 5 and {max_length} characters.")
    if any(
        unicodedata.category(character) == "Cc" and character not in "\r\n\t"
        for character in value
    ):
        raise ValidationError(f"{label} contains unsupported characters.")
    if not any(character.isalnum() for character in value):
        raise ValidationError(f"Enter a complete {label.lower()}.")
    return value


def validate_email_address(value):
    if not isinstance(value, str):
        raise ValidationError("Enter a valid email address.")
    value = value.strip().lower()
    if len(value) > 254:
        raise ValidationError("Email addresses cannot exceed 254 characters.")
    try:
        validate_email(value)
    except ValidationError:
        raise ValidationError("Enter a valid email address.") from None
    return value


def validate_http_url(value, *, required=False, max_length=1000):
    if not isinstance(value, str):
        raise ValidationError("Enter a valid URL.")
    value = value.strip()
    if not value and not required:
        return ""
    if len(value) > max_length:
        raise ValidationError(f"URLs cannot exceed {max_length} characters.")
    try:
        URLValidator(schemes=["http", "https"])(value)
    except ValidationError:
        raise ValidationError("Enter a valid URL beginning with http:// or https://.") from None
    return value


def validate_amount(value, *, label="Amount", allow_zero=False, max_value=Decimal("9999999999.99")):
    if isinstance(value, bool):
        raise ValidationError(f"Enter a valid {label.lower()}.")
    text = str(value).strip()
    if not _AMOUNT_PATTERN.fullmatch(text):
        raise ValidationError(f"{label} must be a non-negative number with no more than 2 decimal places.")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Enter a valid {label.lower()}.") from None
    if not amount.is_finite() or amount > max_value or (amount < 0 if allow_zero else amount <= 0):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise ValidationError(f"{label} must be {qualifier} and within the allowed limit.")
    return amount.quantize(Decimal("0.01"))


def validate_whole_number(value, *, label="Value", minimum=0, maximum=999999):
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a whole number.")
    text = str(value).strip()
    if not _INTEGER_PATTERN.fullmatch(text):
        raise ValidationError(f"{label} must be a whole number using digits only.")
    number = int(text)
    if not minimum <= number <= maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}.")
    return number


def validate_sku(value):
    value = validate_business_name(value, label="SKU", max_length=64)
    if not _SKU_PATTERN.fullmatch(value):
        raise ValidationError("SKU may contain letters, numbers, periods, underscores, slashes, and hyphens.")
    return value


def validate_vehicle_identifier(value, *, label="Vehicle number", required=False):
    value = validate_business_name(value, label=label, max_length=32, required=required)
    if value and not _VEHICLE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValidationError(f"{label} may contain letters, numbers, spaces, slashes, and hyphens.")
    return value


def validate_license_identifier(value, *, required=True):
    value = validate_business_name(value, label="Driving license number", max_length=50, required=required)
    if value and not _LICENSE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValidationError("Enter a valid driving license number.")
    return value


def validate_password_strength(password, *, user=None):
    if not isinstance(password, str):
        raise ValidationError("Enter a valid password.")
    requirements = (
        (len(password) >= 8, "Use at least 8 characters."),
        (any(character.isupper() for character in password), "Include at least one uppercase letter."),
        (any(character.islower() for character in password), "Include at least one lowercase letter."),
        (any(character.isdigit() for character in password), "Include at least one number."),
        (any(not character.isalnum() for character in password), "Include at least one special character."),
    )
    errors = [message for valid, message in requirements if not valid]
    if errors:
        raise ValidationError(errors)
    try:
        validate_password(password, user=user)
    except ValidationError as error:
        raise ValidationError(error.messages) from None
    return password

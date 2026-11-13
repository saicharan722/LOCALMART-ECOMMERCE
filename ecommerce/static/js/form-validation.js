(function () {
    "use strict";

    const phonePattern = /^[6-9][0-9]{9}$/;
    const personNamePattern = /^[\p{L}\p{M}][\p{L}\p{M} .'-]{1,149}$/u;
    const pricePattern = /^[0-9]+(?:\.[0-9]{1,2})?$/;
    const integerPattern = /^[0-9]+$/;
    let nextErrorId = 0;

    function fieldContext(field) {
        const label = Array.from(field.labels || [])
            .map(element => element.textContent || "")
            .join(" ");
        const text = [
            field.name,
            field.id,
            field.getAttribute("aria-label"),
            field.getAttribute("placeholder"),
            label
        ].filter(Boolean).join(" ").toLowerCase();

        if (field.type === "password") {
            return /confirm|repeat|again|new_password2/.test(text)
                ? "password-confirm"
                : "password";
        }
        if (/pin.?code|postal.?code|post.?code|zip.?code/.test(text)) return "postal-code";
        if (field.type === "tel" || /phone|mobile|telephone/.test(text)) return "phone";
        if (/address|street/.test(text)) return "address";
        if (/price|amount|cost/.test(text)) return "price";
        if (/quantity|stock|inventory/.test(text)) return "integer";
        if (/driving.?license|license.?number/.test(text)) return "license";
        if (/vehicle.?number|registration.?number/.test(text)) return "vehicle-number";
        if (/sku/.test(text)) return "sku";
        if (/full name|first name|last name|owner name|customer name|partner name|customer[_-]?name/.test(text)) return "person-name";
        if (field.type === "email") return "email";
        if (field.type === "url") return "url";
        return "default";
    }

    function prepareField(field) {
        if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement)) return;
        if (field.type === "hidden" || field.type === "submit" || field.type === "button" || field.type === "reset") return;

        const kind = fieldContext(field);
        field.dataset.validationKind = kind;

        if (kind === "phone") {
            field.inputMode = "numeric";
            field.pattern = "[6-9][0-9]{9}";
            field.maxLength = 10;
            field.title = "Enter a 10-digit mobile number using digits only.";
        } else if (kind === "postal-code") {
            field.inputMode = "numeric";
            field.pattern = "[1-9][0-9]{5}";
            field.maxLength = 6;
            field.title = "Enter a valid 6-digit PIN code.";
        } else if (kind === "price") {
            field.inputMode = "decimal";
            if (field.type === "number") {
                field.step = "0.01";
                if (!field.hasAttribute("min")) field.min = "0";
                if (!field.hasAttribute("max")) field.max = "9999999999.99";
            }
        } else if (kind === "person-name" && !field.hasAttribute("maxlength")) {
            field.maxLength = 150;
        } else if (kind === "address" && !field.hasAttribute("maxlength")) {
            field.maxLength = 1000;
        } else if (kind === "email" && !field.hasAttribute("maxlength")) {
            field.maxLength = 254;
        } else if (kind === "url" && !field.hasAttribute("maxlength")) {
            field.maxLength = 1000;
        } else if (kind === "vehicle-number" && !field.hasAttribute("maxlength")) {
            field.maxLength = 32;
        } else if (kind === "license" && !field.hasAttribute("maxlength")) {
            field.maxLength = 50;
        } else if (kind === "sku" && !field.hasAttribute("maxlength")) {
            field.maxLength = 64;
        } else if (kind === "integer" && field.type === "number") {
            field.step = "1";
            if (!field.hasAttribute("min")) field.min = field.name.toLowerCase().includes("stock") ? "0" : "1";
        }
    }

    function requiredMessage(field) {
        const label = Array.from(field.labels || [])
            .map(element => element.textContent.trim())
            .find(Boolean);
        const name = label || field.getAttribute("aria-label") || field.placeholder || "This field";
        return `${name.replace(/[*:]\s*$/, "")} is required.`;
    }

    function passwordPolicyApplies(field) {
        const form = field.form;
        return field.autocomplete === "new-password"
            || (form && ["signupForm", "merchantRegisterForm"].includes(form.id))
            || Boolean(form && form.classList.contains("partner-form"));
    }

    function passwordError(password) {
        if (password.length < 8) return "Use at least 8 characters.";
        if (!/[A-Z]/.test(password)) return "Include at least one uppercase letter.";
        if (!/[a-z]/.test(password)) return "Include at least one lowercase letter.";
        if (!/[0-9]/.test(password)) return "Include at least one number.";
        if (!/[^A-Za-z0-9]/.test(password)) return "Include at least one special character.";
        return "";
    }

    function getMessage(field) {
        const value = field.value.trim();
        const kind = field.dataset.validationKind || fieldContext(field);
        if (field.required && (field.type === "checkbox" ? !field.checked : !value)) {
            return requiredMessage(field);
        }
        if (!value) return "";

        if (kind === "phone" && !phonePattern.test(value)) {
            return "Enter a valid 10-digit mobile number using digits only.";
        }
        if (kind === "postal-code" && !/^[1-9][0-9]{5}$/.test(value)) {
            return "Enter a valid 6-digit PIN code.";
        }
        if (kind === "person-name" && !personNamePattern.test(value)) {
            return "Use 2-150 letters, spaces, apostrophes, periods, or hyphens.";
        }
        if (kind === "vehicle-number" && !/^[A-Za-z0-9][A-Za-z0-9 /-]{2,31}$/.test(value)) {
            return "Enter a valid vehicle number using letters, numbers, spaces, slashes, or hyphens.";
        }
        if (kind === "license" && !/^[A-Za-z0-9][A-Za-z0-9 /-]{3,49}$/.test(value)) {
            return "Enter a valid driving license number.";
        }
        if (kind === "sku" && !/^[A-Za-z0-9][A-Za-z0-9._/-]{1,63}$/.test(value)) {
            return "SKU must contain 2-64 letters, numbers, periods, underscores, slashes, or hyphens.";
        }
        if (kind === "address" && value.length < 5) {
            return "Enter a complete address of at least 5 characters.";
        }
        if (kind === "price" && !pricePattern.test(value)) {
            return "Enter a valid amount with no more than 2 decimal places.";
        }
        if (kind === "integer" && !integerPattern.test(value)) {
            return "Enter a whole number using digits only.";
        }
        if (kind === "password" && passwordPolicyApplies(field)) {
            return passwordError(field.value);
        }
        if (kind === "password-confirm") {
            const passwordField = Array.from(field.form ? field.form.querySelectorAll('input[type="password"]') : [])
                .find(input => input !== field && !/confirm|repeat|again|new_password2/i.test(`${input.name} ${input.id}`));
            if (passwordField && field.value !== passwordField.value) return "The passwords do not match.";
        }
        if (kind === "url") {
            try {
                const url = new URL(value);
                if (url.protocol !== "http:" && url.protocol !== "https:") return "Enter a URL beginning with http:// or https://.";
            } catch (_) {
                return "Enter a valid URL beginning with http:// or https://.";
            }
        }
        if (field.validity.typeMismatch) {
            return kind === "email" ? "Enter a valid email address." : "Enter a valid value.";
        }
        if (field.validity.rangeUnderflow) return `Enter a value of at least ${field.min}.`;
        if (field.validity.rangeOverflow) return `Enter a value no greater than ${field.max}.`;
        if (field.validity.stepMismatch) return "Enter a value in the accepted increments.";
        if (field.validity.patternMismatch) return field.title || "Enter a value in the required format.";
        return "";
    }

    function errorElement(field) {
        if (field.dataset.validationErrorId) {
            return document.getElementById(field.dataset.validationErrorId);
        }
        const error = document.createElement("div");
        error.id = `form-validation-error-${++nextErrorId}`;
        error.className = "invalid-feedback d-block";
        error.setAttribute("role", "alert");
        const anchor = field.closest(".input-group") || field;
        anchor.insertAdjacentElement("afterend", error);
        field.dataset.validationErrorId = error.id;
        return error;
    }

    function updateDescribedBy(field, errorId, add) {
        const ids = new Set((field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
        if (add) ids.add(errorId);
        else ids.delete(errorId);
        if (ids.size) field.setAttribute("aria-describedby", Array.from(ids).join(" "));
        else field.removeAttribute("aria-describedby");
    }

    function validateField(field, showError, forcedMessage) {
        prepareField(field);
        const message = forcedMessage === undefined ? getMessage(field) : forcedMessage;
        field.setCustomValidity(message);
        const isValid = !message && field.validity.valid;
        if (showError || field.dataset.validationTouched === "true") {
            if (isValid) {
                field.classList.remove("is-invalid");
                field.removeAttribute("aria-invalid");
                const id = field.dataset.validationErrorId;
                if (id) {
                    updateDescribedBy(field, id, false);
                    const error = document.getElementById(id);
                    if (error) error.remove();
                    delete field.dataset.validationErrorId;
                }
            } else {
                field.classList.add("is-invalid");
                field.setAttribute("aria-invalid", "true");
                const error = errorElement(field);
                error.textContent = message || "Please check this value.";
                updateDescribedBy(field, error.id, true);
            }
        }
        return isValid;
    }

    function validatePriceRange(form, showError) {
        const minField = form.querySelector('[name="min_price"], [name="price_min"]');
        const maxField = form.querySelector('[name="max_price"], [name="price_max"]');
        if (!minField || !maxField || !minField.value || !maxField.value) return true;
        const invalid = Number(maxField.value) < Number(minField.value);
        if (invalid && showError) maxField.dataset.validationTouched = "true";
        const valid = validateField(
            maxField,
            showError,
            invalid ? "Maximum price must be greater than or equal to minimum price." : undefined
        );
        return valid;
    }

    function validateFields(fields) {
        let valid = true;
        fields.filter(Boolean).forEach(field => {
            field.dataset.validationTouched = "true";
            if (!validateField(field, true)) valid = false;
        });
        if (!valid) {
            const firstInvalid = fields.find(field => field && !field.validity.valid);
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.reportValidity();
            }
        }
        return valid;
    }

    document.addEventListener("input", event => {
        if (!(event.target instanceof HTMLElement) || !("value" in event.target)) return;
        const field = event.target;
        if (field.dataset.validationKind === "phone" && /[^0-9]/.test(field.value)) {
            field.dataset.validationTouched = "true";
        }
        validateField(field, false);
    });

    document.addEventListener("blur", event => {
        if (event.target instanceof HTMLElement && "value" in event.target) {
            event.target.dataset.validationTouched = "true";
            validateField(event.target, true);
        }
    }, true);

    document.addEventListener("beforeinput", event => {
        const field = event.target;
        if (field instanceof HTMLInputElement && fieldContext(field) === "phone"
            && event.data && /[^0-9]/.test(event.data)
            && event.inputType && event.inputType.startsWith("insert")) {
            event.preventDefault();
            field.dataset.validationTouched = "true";
            validateField(field, true, "Mobile numbers can contain digits only.");
        }
    });

    document.addEventListener("paste", event => {
        const field = event.target;
        if (!(field instanceof HTMLInputElement) || fieldContext(field) !== "phone") return;
        const pasted = event.clipboardData && event.clipboardData.getData("text");
        if (pasted && /[^0-9]/.test(pasted)) {
            event.preventDefault();
            field.dataset.validationTouched = "true";
            validateField(field, true, "Mobile numbers can contain digits only.");
        }
    });

    document.addEventListener("submit", event => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        const fields = Array.from(form.elements)
            .filter(field => field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement)
            .filter(field => field.type !== "hidden" && !field.disabled);
        let valid = true;
        fields.forEach(field => {
            field.dataset.validationTouched = "true";
            if (!validateField(field, true)) valid = false;
        });
        if (!validatePriceRange(form, true)) valid = false;
        if (!form.checkValidity()) valid = false;
        if (!valid) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const firstInvalid = fields.find(field => !field.validity.valid);
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.reportValidity();
            }
        }
    }, true);

    document.querySelectorAll("input, textarea, select").forEach(prepareField);
    window.LocalMartFormValidation = {validateFields};
    new MutationObserver(records => records.forEach(record => {
        record.addedNodes.forEach(node => {
            if (node instanceof HTMLElement) {
                if (node.matches("input, textarea, select")) prepareField(node);
                node.querySelectorAll("input, textarea, select").forEach(prepareField);
            }
        });
    })).observe(document.documentElement, {childList: true, subtree: true});
})();

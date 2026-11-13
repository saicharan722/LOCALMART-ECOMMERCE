"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const container = document.getElementById("cartContainer");
    const countElement = document.getElementById("cartItemCount");
    const subtotalElement = document.getElementById("subtotal");
    const taxElement = document.getElementById("tax");
    const totalElement = document.getElementById("grandTotal");
    const messageElement = document.getElementById("cartMessage");
    const clearButton = document.getElementById("clearCartButton");
    const itemsColumn = document.getElementById("cartItemsColumn");
    const summaryColumn = document.getElementById("cartSummaryColumn");
    const checkoutButton = document.getElementById("proceedToCheckoutButton");
    const checkoutNotice = document.getElementById("checkoutAvailabilityNotice");
    const couponCodeInput = document.getElementById("couponCode");
    const applyCouponButton = document.getElementById("applyCouponButton");
    const couponDiscountRow = document.getElementById("couponDiscountRow");
    const couponDiscountElement = document.getElementById("couponDiscount");
    const couponMessageElement = document.getElementById("couponMessage");
    const appliedCouponElement = document.getElementById("appliedCoupon");
    const availableCouponsElement = document.getElementById("availableCoupons");
    const availableCouponCountElement = document.getElementById("availableCouponCount");
    const couponCatalogNotice = document.getElementById("couponCatalogNotice");

    if (!container) return;

    const homeUrl = container.dataset.homeUrl || "/";

    const csrfToken = () => document.cookie
        .split(";")
        .map(value => value.trim())
        .find(value => value.startsWith("csrftoken="))
        ?.slice("csrftoken=".length) || "";

    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);

    const money = value => `₹${Number(value || 0).toFixed(2)}`;
    const isCartStorageKey = key =>
        key.toLowerCase() === "cart" || key.toLowerCase().endsWith("cart");

    function getCartStorageKeys() {
        return Array.from(
            { length: localStorage.length },
            (_, index) => localStorage.key(index)
        ).filter(key => key && isCartStorageKey(key));
    }

    function getLocalCartItems() {
        const items = [];

        getCartStorageKeys().forEach(key => {
            let savedItems;
            try {
                savedItems = JSON.parse(localStorage.getItem(key) || "[]");
            } catch (error) {
                console.error(`Unable to read ${key}:`, error);
                return;
            }

            if (!Array.isArray(savedItems)) return;

            savedItems.forEach((item, index) => {
                if (!item || typeof item !== "object" || Array.isArray(item)) return;

                const name = item.name || item.title || item.product_name;
                const price = Number(item.price ?? item.sellingPrice ?? item.discountedPrice);
                if (!name || !Number.isFinite(price) || price < 0) return;

                const restaurantName = item.restaurantName || item.restaurant_name || "";
                const keyName = key.toLowerCase();
                const category = restaurantName
                    ? "Food"
                    : item.category ||
                        (keyName.includes("fashion") || keyName.includes("shopping")
                            ? "Shopping"
                            : keyName.includes("grocery") || keyName === "cart"
                                ? keyName === "cart" ? "Food" : "Grocery"
                                : "LocalMart");
                const quantity = Math.max(1, Math.floor(Number(item.quantity) || 1));

                items.push({
                    ...item,
                    name: String(name),
                    category,
                    restaurantName,
                    price,
                    quantity,
                    subtotal: price * quantity,
                    _cartStorageKey: key,
                    _cartStorageIndex: index
                });
            });
        });

        return items;
    }

    function setMessage(message, isError = false) {
        if (!messageElement) return;
        messageElement.textContent = message;
        messageElement.className = isError
            ? "alert alert-danger"
            : "alert alert-success";
        messageElement.hidden = !message;
    }

    function setCouponMessage(message, isError = false) {
        if (!couponMessageElement) return;
        couponMessageElement.textContent = message;
        couponMessageElement.className = isError
            ? "small mt-2 text-danger"
            : "small mt-2 text-success";
    }

    function updateCounts(count) {
        document.querySelectorAll(
            "#cartCount, #navbarCartCount, #cart-count, .cart-count, [data-cart-count]"
        )
            .forEach(element => {
                element.textContent = String(count);
                element.setAttribute("aria-label", `${count} items in cart`);
            });
        if (countElement) {
            countElement.textContent = `${count} ${count === 1 ? "item" : "items"}`;
        }
        window.dispatchEvent(new CustomEvent("localmart:cart-updated", {
            detail: { count }
        }));
    }

    async function request(url, method = "GET", body) {
        const headers = { "X-Requested-With": "XMLHttpRequest" };
        if (body !== undefined) headers["Content-Type"] = "application/json";
        if (method !== "GET") headers["X-CSRFToken"] = csrfToken();
        const response = await fetch(url, {
            method,
            headers,
            body: body === undefined ? undefined : JSON.stringify(body),
            credentials: "same-origin"
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || "Unable to update your cart.");
        }
        return data;
    }

    function render(data) {
        const serverItems = Array.isArray(data.items) ? data.items : [];
        const localItems = getLocalCartItems();
        const items = serverItems.concat(localItems);
        const itemCount = items.reduce(
            (count, item) => count + (Number(item.quantity) || 1),
            0
        );
        const subtotal = items.reduce(
            (amount, item) =>
                amount + (Number(item.price) || 0) * (Number(item.quantity) || 1),
            0
        );
        const localSubtotal = localItems.reduce(
            (amount, item) =>
                amount + (Number(item.price) || 0) * (Number(item.quantity) || 1),
            0
        );
        const coupon = data.coupon || null;
        const couponDiscount = coupon?.eligible
            ? Number(data.coupon_discount) || 0
            : 0;
        const serverTotal = Number(data.total);
        const tax = (Number(data.tax) || 0) + localSubtotal * 0.05;
        const total = Number.isFinite(serverTotal)
            ? serverTotal + localSubtotal * 1.05
            : subtotal + tax;
        const hasItems = items.length > 0;
        updateCounts(itemCount);
        if (subtotalElement) subtotalElement.textContent = money(subtotal);
        if (taxElement) taxElement.textContent = money(tax);
        if (totalElement) totalElement.textContent = money(total);
        if (couponDiscountRow) couponDiscountRow.hidden = couponDiscount <= 0;
        if (couponDiscountElement) couponDiscountElement.textContent = `−${money(couponDiscount)}`;
        if (couponCatalogNotice) couponCatalogNotice.hidden = localItems.length === 0;
        if (itemsColumn) itemsColumn.classList.toggle("col-lg-8", hasItems);
        if (summaryColumn) summaryColumn.hidden = !hasItems;
        if (clearButton) clearButton.hidden = !hasItems;
        if (checkoutButton) checkoutButton.disabled = !hasItems;
        if (checkoutNotice) checkoutNotice.hidden = localItems.length === 0;
        renderAppliedCoupon(coupon);
        renderAvailableCoupons(data.available_coupons || []);

        if (!hasItems) {
            container.innerHTML = `
                <div class="cart-empty">
                    <i class="bi bi-cart-x" aria-hidden="true"></i>
                    <h4 class="fw-bold">Your cart is empty</h4>
                    <p class="text-muted">Add products from any LocalMart category to see them here.</p>
                    <a href="${escapeHtml(homeUrl)}" class="btn btn-success">Continue shopping</a>
                </div>`;
            return;
        }

        container.innerHTML = items.map(item => `
            <article class="cart-item">
                <img src="${escapeHtml(item.image || "https://via.placeholder.com/160?text=Product")}" alt="${escapeHtml(item.name)}"
                     onerror="this.onerror=null;this.src='https://via.placeholder.com/160?text=Product'">
                <div class="cart-item-details">
                    <h5>${escapeHtml(item.name)}</h5>
                    <div class="text-muted small">${escapeHtml(item.category || "LocalMart")}</div>
                    ${item.merchant_name ? `<div class="text-muted small">Sold by ${escapeHtml(item.merchant_name)}</div>` : ""}
                    <div class="cart-item-price">${money(item.price)} <small class="text-muted">each</small></div>
                    <div class="quantity-control">
                        <button class="btn btn-sm btn-outline-secondary" type="button"
                                data-cart-action="decrease" ${item._cartStorageKey
                                    ? `data-cart-source="local" data-cart-key="${escapeHtml(item._cartStorageKey)}" data-cart-index="${item._cartStorageIndex}"`
                                    : `data-cart-source="server" data-item-id="${item.item_id}"`}
                                ${item.quantity <= 1 ? "disabled" : ""} aria-label="Decrease quantity">−</button>
                        <span aria-live="polite">${item.quantity}</span>
                        <button class="btn btn-sm btn-outline-secondary" type="button"
                                data-cart-action="increase" ${item._cartStorageKey
                                    ? `data-cart-source="local" data-cart-key="${escapeHtml(item._cartStorageKey)}" data-cart-index="${item._cartStorageIndex}"`
                                    : `data-cart-source="server" data-item-id="${item.item_id}"`}
                                ${item.quantity >= (item.stock == null ? 99 : Number(item.stock)) ? "disabled" : ""} aria-label="Increase quantity">+</button>
                    </div>
                    <div class="small text-muted mt-2">Subtotal: <strong>${money(item.subtotal ?? item.price * item.quantity)}</strong></div>
                </div>
                <button class="btn btn-outline-danger btn-sm align-self-start" type="button"
                        data-cart-action="remove" ${item._cartStorageKey
                            ? `data-cart-source="local" data-cart-key="${escapeHtml(item._cartStorageKey)}" data-cart-index="${item._cartStorageIndex}"`
                            : `data-cart-source="server" data-item-id="${item.item_id}"`}>
                    <i class="bi bi-trash" aria-hidden="true"></i> Remove
                </button>
            </article>`).join("");
    }

    function renderAppliedCoupon(coupon) {
        if (!appliedCouponElement) return;
        if (!coupon?.code) {
            appliedCouponElement.hidden = true;
            appliedCouponElement.innerHTML = "";
            return;
        }

        const status = coupon.eligible
            ? `You saved ${money(coupon.discount_amount)} with this offer.`
            : coupon.reason || "This coupon is no longer eligible.";
        const categoryScope = coupon.eligible_categories?.length
            ? `Applicable to ${coupon.eligible_categories.join(", ")}`
            : "Applicable to all categories";
        appliedCouponElement.hidden = false;
        appliedCouponElement.innerHTML = `
            <div class="d-flex justify-content-between align-items-start gap-2 rounded border p-3">
                <div>
                    <strong>${escapeHtml(coupon.code)}</strong>
                    <div class="small ${coupon.eligible ? "text-success" : "text-danger"}">${escapeHtml(status)}</div>
                    <div class="small text-muted">${escapeHtml(categoryScope)}</div>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger" data-remove-coupon>Remove</button>
            </div>`;
    }

    function renderAvailableCoupons(coupons) {
        if (!availableCouponsElement) return;
        if (availableCouponCountElement) {
            availableCouponCountElement.textContent = String(coupons.length);
        }
        if (!coupons.length) {
            availableCouponsElement.innerHTML = '<p class="small text-muted mb-0">No coupon offers are available right now.</p>';
            return;
        }

        availableCouponsElement.innerHTML = coupons.map(coupon => {
            const offer = coupon.discount_type === "percentage"
                ? `${escapeHtml(coupon.discount_value)}% off`
                : `${money(coupon.discount_value)} off`;
            const hasCategoryRestriction = Boolean(coupon.eligible_categories?.length);
            const minimum = Number(coupon.minimum_order_amount) > 0
                ? `Minimum ${hasCategoryRestriction ? "eligible spend" : "order"} ${money(coupon.minimum_order_amount)}`
                : "No minimum order";
            const cap = coupon.maximum_discount_amount
                ? ` · Max discount ${money(coupon.maximum_discount_amount)}`
                : "";
            const categories = coupon.eligible_categories?.length
                ? `Applies to ${coupon.eligible_categories.join(", ")}`
                : "All categories";
            const expiry = coupon.expires_at
                ? ` · Expires ${new Date(coupon.expires_at).toLocaleDateString()}`
                : "";
            const terms = `${categories} · ${minimum}${cap}${expiry}`;
            return `
                <article class="rounded border p-3 mb-2">
                    <div class="d-flex justify-content-between align-items-start gap-2">
                        <div>
                            <strong>${escapeHtml(coupon.code)}</strong>
                            <span class="badge text-bg-success ms-1">${offer}</span>
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-success"
                                data-apply-coupon="${escapeHtml(coupon.code)}"
                                ${coupon.eligible ? "" : "disabled"}>
                            Apply
                        </button>
                    </div>
                    <p class="small mb-1 mt-2">${escapeHtml(coupon.description)}</p>
                    <p class="small text-muted mb-0">${escapeHtml(terms)}</p>
                    ${coupon.eligible ? "" : `<p class="small text-danger mb-0 mt-1">${escapeHtml(coupon.reason)}</p>`}
                </article>`;
        }).join("");
    }

    async function syncLocalItems() {
        const localItems = getLocalCartItems();
        if (!localItems.length) return;
        const data = await request("/api/cart/import-local/", "POST", {
            items: localItems.map(item => ({
                name: item.name,
                category: item.category,
                brand: item.brand || "",
                price: item.price,
                image: item.image || "",
                quantity: item.quantity
            }))
        });
        clearLocalCart();
        render(data);
    }

    async function loadCouponData(preserveMessage = false) {
        let syncError = "";
        try {
            await syncLocalItems();
        } catch (error) {
            syncError = error.message;
        }
        try {
            const data = await request("/api/cart/coupon/");
            render(data);
            if (syncError) setCouponMessage(syncError, true);
            else if (!preserveMessage) setCouponMessage("");
        } catch (error) {
            setCouponMessage(error.message, true);
        }
    }

    async function refresh() {
        let data;
        try {
            setMessage("");
            data = await request("/api/cart/");
        } catch (error) {
            setMessage(error.message, true);
            data = { items: [], item_count: 0, subtotal: 0 };
        }
        render(data);
        await loadCouponData();
    }

    function updateLocalCart(key, index, action) {
        const savedItems = JSON.parse(localStorage.getItem(key) || "[]");
        if (!Array.isArray(savedItems) || !savedItems[index]) {
            throw new Error("This cart item could not be found. Please refresh the cart.");
        }

        if (action === "remove") {
            savedItems.splice(index, 1);
        } else {
            const item = savedItems[index];
            const quantity = Math.max(1, Math.floor(Number(item.quantity) || 1));
            const nextQuantity = quantity + (action === "increase" ? 1 : -1);
            if (nextQuantity < 1) return;
            const maxQuantity = item.stock == null ? 99 : Number(item.stock);
            if (nextQuantity > maxQuantity) {
                throw new Error(`Only ${maxQuantity} item(s) are available.`);
            }
            item.quantity = nextQuantity;
        }

        localStorage.setItem(key, JSON.stringify(savedItems));
    }

    container.addEventListener("click", async event => {
        const button = event.target.closest("[data-cart-action]");
        if (!button) return;
        const action = button.dataset.cartAction;
        button.disabled = true;
        try {
            if (button.dataset.cartSource === "local") {
                updateLocalCart(
                    button.dataset.cartKey,
                    Number(button.dataset.cartIndex),
                    action
                );
                await refresh();
                setMessage(action === "remove" ? "Product removed from cart." : "");
            } else {
                const itemId = button.dataset.itemId;
                if (action === "remove") {
                    await request(`/api/cart/items/${itemId}/`, "DELETE");
                    await loadCouponData();
                    setMessage("Product removed from cart.");
                    return;
                }
                const current = await request("/api/cart/");
                const item = current.items.find(value => String(value.item_id) === itemId);
                if (!item) return refresh();
                const quantity = item.quantity + (action === "increase" ? 1 : -1);
                if (quantity < 1) return;
                await request(`/api/cart/items/${itemId}/`, "PATCH", { quantity });
                await loadCouponData();
                setMessage("");
            }
        } catch (error) {
            await refresh();
            setMessage(error.message, true);
        } finally {
            button.disabled = false;
        }
    });

    function clearLocalCart() {
        getCartStorageKeys().forEach(key => localStorage.removeItem(key));
    }

    clearButton?.addEventListener("click", async () => {
        if (!window.confirm("Clear all products from your cart?")) return;
        clearButton.disabled = true;
        try {
            const data = await request("/api/cart/", "DELETE");
            clearLocalCart();
            render(data);
            await loadCouponData();
            setMessage("Your cart has been cleared.");
        } catch (error) {
            setMessage(error.message, true);
        } finally {
            clearButton.disabled = false;
        }
    });

    async function applyCoupon(code) {
        if (applyCouponButton) applyCouponButton.disabled = true;
        try {
            await syncLocalItems();
            const data = await request("/api/cart/coupon/", "POST", { code });
            render(data);
            await loadCouponData(true);
            setCouponMessage(data.message || `Coupon ${code.toUpperCase()} applied.`);
        } catch (error) {
            setCouponMessage(error.message, true);
        } finally {
            if (applyCouponButton) applyCouponButton.disabled = false;
        }
    }

    applyCouponButton?.addEventListener("click", () => {
        applyCoupon(couponCodeInput?.value || "");
    });

    couponCodeInput?.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            applyCoupon(couponCodeInput.value);
        }
    });

    availableCouponsElement?.addEventListener("click", event => {
        const button = event.target.closest("[data-apply-coupon]");
        if (!button || button.disabled) return;
        if (couponCodeInput) couponCodeInput.value = button.dataset.applyCoupon;
        applyCoupon(button.dataset.applyCoupon);
    });

    appliedCouponElement?.addEventListener("click", async event => {
        if (!event.target.closest("[data-remove-coupon]")) return;
        try {
            const data = await request("/api/cart/coupon/", "DELETE");
            render(data);
            await loadCouponData(true);
            setCouponMessage(data.message || "Coupon removed.");
        } catch (error) {
            setCouponMessage(error.message, true);
        }
    });

    checkoutButton?.addEventListener("click", async () => {
        if (checkoutButton.disabled) return;
        checkoutButton.disabled = true;
        try {
            await syncLocalItems();
            window.location.href = "/checkout/";
        } catch (error) {
            setMessage(error.message, true);
            checkoutButton.disabled = false;
        }
    });

    window.addEventListener("storage", event => {
        if (!event.key || isCartStorageKey(event.key)) refresh();
    });

    refresh();
});

(function () {
    "use strict";
    if (window.localmartAddUnifiedCart) return;

    let serverCartCount = 0;

    function csrfToken() {
        const cookie = document.cookie
            .split(";")
            .map(value => value.trim())
            .find(value => value.startsWith("csrftoken="));
        return cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "";
    }

    function renderCartCount() {
        const localCount = Array.from(
            { length: localStorage.length },
            (_, index) => localStorage.key(index)
        )
            .filter(key => key && (key.toLowerCase() === "cart" || key.toLowerCase().endsWith("cart")))
            .reduce((total, key) => {
                try {
                    const items = JSON.parse(localStorage.getItem(key) || "[]");
                    if (!Array.isArray(items)) return total;
                    return total + items.reduce(
                        (subtotal, item) => {
                            const quantity = Number(item && item.quantity);
                            return subtotal + (
                                Number.isFinite(quantity) && quantity > 0
                                    ? quantity
                                    : 1
                            );
                        },
                        0
                    );
                } catch (error) {
                    console.error(`Unable to read ${key}:`, error);
                    return total;
                }
            }, 0);

        document.querySelectorAll(
            "#cartCount, #navbarCartCount, #cart-count, .cart-count, [data-cart-count]"
        ).forEach(element => {
            element.textContent = String(serverCartCount + localCount);
        });
    }

    async function refreshCartCount() {
        try {
            const response = await fetch("/api/cart/count/", {
                credentials: "same-origin",
                headers: { "Accept": "application/json" }
            });
            if (!response.ok) throw new Error("Unable to load cart count.");
            const data = await response.json();
            serverCartCount = Number(data.count) || 0;
            renderCartCount();
        } catch (error) {
            console.error("Unified cart count refresh failed:", error);
            renderCartCount();
        }
    }

    let countRefresh = Promise.resolve();

    window.localmartAddUnifiedCart = async function (catalogKey, quantity = 1) {
        try {
            await countRefresh;
            const response = await fetch("/api/cart/items/", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken()
                },
                body: JSON.stringify({
                    source: "catalog",
                    product_id: String(catalogKey),
                    quantity: Number(quantity)
                })
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || "Unable to add this product.");
            }
            serverCartCount = Number(data.item_count) || 0;
            renderCartCount();
            window.dispatchEvent(new CustomEvent("localmart:cart-updated", {
                detail: data
            }));
            return data;
        } catch (error) {
            console.error("Unified cart add failed:", error);
            renderCartCount();
            return null;
        }
    };

    function syncServerCartCount(event) {
        const count = Number(event.detail && event.detail.item_count);
        if (Number.isFinite(count)) {
            serverCartCount = count;
        } else if (Number.isFinite(Number(event.detail && event.detail.count))) {
            const combinedCount = Number(event.detail.count);
            document.querySelectorAll(
                "#cartCount, #navbarCartCount, #cart-count, .cart-count, [data-cart-count]"
            ).forEach(element => {
                element.textContent = String(combinedCount);
                element.setAttribute("aria-label", `${combinedCount} items in cart`);
            });
            return;
        }
        renderCartCount();
    }

    window.addEventListener("storage", renderCartCount);
    window.addEventListener("groceryCartUpdated", renderCartCount);
    window.addEventListener("localmart:cart-updated", syncServerCartCount);

    document.addEventListener("DOMContentLoaded", () => {
        countRefresh = refreshCartCount();
    });
})();

(() => {
    const ordersPage = document.querySelector(".orders-main[data-status-url]");
    if (!ordersPage) return;

    const orderCards = new Map(
        Array.from(ordersPage.querySelectorAll("[data-order-id]"))
            .map((card) => [card.dataset.orderId, card.dataset.statusSnapshot])
    );

    async function refreshOrderStatuses() {
        try {
            const response = await fetch(ordersPage.dataset.statusUrl, {
                credentials: "same-origin",
                headers: { "Accept": "application/json" },
                cache: "no-store",
            });
            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }
            if (!response.ok) {
                throw new Error(`Order status refresh failed (${response.status}).`);
            }

            const data = await response.json();
            if (!Array.isArray(data.orders)) {
                throw new Error("Order status refresh returned an invalid response.");
            }

            if (data.orders.length !== orderCards.size) {
                window.location.reload();
                return;
            }

            for (const order of data.orders) {
                if (orderCards.get(String(order.id)) !== order.snapshot) {
                    window.location.reload();
                    return;
                }
            }
        } catch (error) {
            console.warn("Could not refresh order statuses.", error);
        }

        window.setTimeout(refreshOrderStatuses, 10000);
    }

    window.setTimeout(refreshOrderStatuses, 10000);
})();

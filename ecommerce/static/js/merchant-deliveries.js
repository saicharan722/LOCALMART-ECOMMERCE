(() => {
  const root = document.getElementById("merchantDeliveries"), endpoint = window.MERCHANT_DELIVERY_API;
  const csrf = () => document.cookie.split(";").map((x) => x.trim()).find((x) => x.startsWith("csrftoken="))?.slice(10) || "";

  function addDetail(container, label, value) {
    const item = document.createElement("div");
    item.className = "delivery-detail";
    const name = document.createElement("span");
    name.className = "delivery-detail-label";
    name.textContent = label;
    const content = document.createElement("strong");
    content.className = "delivery-detail-value";
    content.textContent = value || "Not available";
    item.append(name, content);
    container.append(item);
  }

  function createDeliveryCard(delivery, partners) {
    const card = document.createElement("article");
    card.className = "card driver-order delivery-card";

    const header = document.createElement("div");
    header.className = "delivery-card-header";
    const title = document.createElement("h2");
    title.className = "delivery-order-title";
    title.textContent = `Order ${delivery.number}`;
    const status = document.createElement("span");
    status.className = "delivery-status-pill";
    status.textContent = delivery.status_label || delivery.status || "Active";
    header.append(title, status);

    const details = document.createElement("div");
    details.className = "delivery-details";
    const partnerName = delivery.partner_name || "Unassigned";
    const partnerId = delivery.partner_id ? `DP-${String(delivery.partner_id).padStart(4, "0")}` : "";
    const vehicle = [delivery.partner_vehicle, delivery.partner_vehicle_number].filter(Boolean).join(" · ");
    addDetail(details, "Customer", delivery.customer);
    addDetail(details, "Order total", `₹${delivery.total}`);
    addDetail(details, "Delivery partner", [partnerName, partnerId].filter(Boolean).join(" · "));
    addDetail(details, "Vehicle", vehicle || (delivery.partner_id ? "Details unavailable" : "Not assigned"));
    addDetail(details, "Contact", delivery.partner_phone || "Not provided");
    addDetail(details, "Partner location", delivery.partner_location || "Waiting for GPS");

    const actions = document.createElement("div");
    actions.className = "delivery-card-actions";
    const actionButtons = document.createElement("div");
    actionButtons.className = "delivery-action-buttons";
    const assignLabel = document.createElement("label");
    assignLabel.className = "delivery-assign";
    const assignText = document.createElement("span");
    assignText.textContent = "Assign available delivery partner";
    const select = document.createElement("select");
    select.className = "delivery-partner-select";
    select.setAttribute("aria-label", "Assign delivery partner");
    const availablePartners = partners.filter((partner) => partner.available);
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = availablePartners.length ? "Choose a partner" : "No available partners";
    select.append(blank);
    availablePartners.forEach((partner) => {
      const option = document.createElement("option");
      option.value = partner.id;
      option.textContent = `${partner.name} (Available)`;
      option.selected = String(partner.id) === String(delivery.partner_id);
      select.append(option);
    });
    select.disabled = !availablePartners.length;
    assignLabel.append(assignText, select);
    actions.append(assignLabel);

    select.addEventListener("change", async () => {
      if (!select.value) return;
      const partnerId = select.value;
      select.disabled = true;
      try {
        const result = await fetch(`/api/merchant/deliveries/${delivery.order_id}/assign/`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({partner_id: partnerId})
        });
        const body = await result.json();
        if (!result.ok) throw new Error(body.error || "Could not assign this delivery partner.");
        await load();
      } catch (error) {
        alert(error.message);
        select.disabled = false;
        select.value = "";
      }
    });

    const nextStatus = delivery.status === "placed" ? "confirmed" : delivery.status === "confirmed" ? "preparing" : null;
    if (nextStatus) {
      const updateStatus = document.createElement("button");
      updateStatus.className = "delivery-action-button secondary";
      updateStatus.type = "button";
      updateStatus.textContent = nextStatus === "confirmed" ? "Confirm order" : "Mark preparing";
      updateStatus.addEventListener("click", async () => {
        updateStatus.disabled = true;
        try {
          const response = await fetch(delivery.status_url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
            body: JSON.stringify({status: nextStatus})
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "Could not update order status.");
          await load();
        } catch (error) {
          alert(error.message);
          updateStatus.disabled = false;
        }
      });
      actionButtons.append(updateStatus);
    }

    const track = document.createElement("a");
    track.className = "delivery-route-link";
    track.href = `/order/${delivery.order_id}/track/`;
    track.textContent = "View live route";
    actionButtons.append(track);
    actions.append(assignLabel, actionButtons);
    card.append(header, details, actions);
    return card;
  }

  async function load() {
    try {
      const response = await fetch(endpoint, {cache: "no-store"}), data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load deliveries.");
      if (!Array.isArray(data.deliveries) || !Array.isArray(data.partners)) throw new Error("Delivery information is unavailable.");
      root.replaceChildren();
      if (!data.deliveries.length) {
        const empty = document.createElement("article");
        empty.className = "delivery-empty-state";
        empty.textContent = "No active deliveries are linked to this store yet.";
        root.append(empty);
      } else {
        data.deliveries.forEach((delivery) => root.append(createDeliveryCard(delivery, data.partners)));
      }
    } catch (error) {
      const message = document.createElement("article");
      message.className = "delivery-empty-state is-error";
      message.textContent = error.message || "Could not load deliveries.";
      root.replaceChildren(message);
    } finally {
      root.setAttribute("aria-busy", "false");
    }
  }

  load();
  window.setInterval(load, 15000);
})();

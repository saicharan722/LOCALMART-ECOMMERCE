(function () {
    "use strict";

    const WISHLIST_KEY = "localmartGroceryWishlist";

    function readList(key) {
        try {
            const value = JSON.parse(localStorage.getItem(key) || "[]");
            return Array.isArray(value) ? value : [];
        } catch (error) {
            return [];
        }
    }

    function updateCounts() {
        const wishlistCount = document.getElementById("wishlistCount");
        if (wishlistCount) wishlistCount.textContent = String(readList(WISHLIST_KEY).length);
    }

    function initializeGroceryChrome() {
        updateCounts();

        const toggle = document.getElementById("groceryNavToggle");
        const actions = document.getElementById("groceryNavActions");
        if (toggle && actions) {
            toggle.addEventListener("click", function () {
                const open = actions.classList.toggle("open");
                toggle.setAttribute("aria-expanded", String(open));
            });
        }

        const searchForm = document.getElementById("groceryNavSearchForm");
        const navSearch = document.getElementById("groceryNavSearch");
        if (searchForm && navSearch) {
            searchForm.addEventListener("submit", function (event) {
                event.preventDefault();
                const query = navSearch.value.trim();
                if (!query) return;
                const pageSearch = document.querySelector(
                    "#productSearch, #searchInput, #grocerySearch, #attaRiceOilDalsSearch, #sweetSearch, [data-grocery-search]"
                );
                if (pageSearch) {
                    pageSearch.value = query;
                    pageSearch.dispatchEvent(new Event("input", { bubbles: true }));
                    pageSearch.dispatchEvent(new Event("keyup", { bubbles: true }));
                    pageSearch.scrollIntoView({ behavior: "smooth", block: "center" });
                } else if (
                    document.getElementById("groceryCategories") &&
                    typeof window.filterGroceryCategories === "function"
                ) {
                    window.filterGroceryCategories(query);
                    document.getElementById("groceryCategories").scrollIntoView({
                        behavior: "smooth",
                        block: "start"
                    });
                } else {
                    window.location.href = "/grocery/?q=" + encodeURIComponent(query);
                }
            });
        }

        const newsletter = document.getElementById("groceryNewsletterForm");
        if (newsletter) {
            newsletter.addEventListener("submit", function (event) {
                event.preventDefault();
                const button = newsletter.querySelector("button");
                if (button) {
                    button.textContent = "Thanks!";
                    button.disabled = true;
                }
            });
        }
    }

    window.addEventListener("storage", updateCounts);
    window.addEventListener("groceryCartUpdated", updateCounts);
    window.addEventListener("groceryWishlistUpdated", updateCounts);
    document.addEventListener("DOMContentLoaded", initializeGroceryChrome);
})();

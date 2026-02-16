(function(){
  function humanLabel(el) {
    const id = el.getAttribute("id");
    if (id) {
      const lbl = document.querySelector(`label[for="${id}"]`);
      if (lbl) return lbl.textContent.trim().replace(/\*$/, "");
    }
    return (el.getAttribute("name") || el.getAttribute("placeholder") || "Required field").trim();
  }

  function validateForm(form, errorBox) {
    const missing = [];
    const required = form.querySelectorAll("[required]");
    required.forEach(el => {
      let ok = true;
      if (el.type === "checkbox") ok = el.checked;
      else ok = !!(el.value || "").trim();

      el.classList.toggle("field-error", !ok);
      if (!ok) missing.push(humanLabel(el));
    });

    const itemRows = form.querySelectorAll(".item-row");
    if (itemRows.length === 0) missing.push("At least 1 item line");

    if (missing.length) {
      errorBox.style.display = "block";
      errorBox.innerHTML =
        `<strong>Please complete the required fields:</strong><ul>` +
        missing.map(m => `<li>${m}</li>`).join("") +
        `</ul>`;
      errorBox.scrollIntoView({ behavior: "smooth", block: "start" });
      return false;
    }

    errorBox.style.display = "none";
    errorBox.innerHTML = "";
    return true;
  }

  async function submitOrder(form, errorBox) {
    if (!validateForm(form, errorBox)) return;

    const btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.disabled = true; btn.dataset._text = btn.textContent; btn.textContent = "Sending..."; }

    try {
      const fd = new FormData(form);

      const itemsTbodyId = form.id === 'quickOrderForm' ? 'q_itemsBody' : 'l_itemsBody';
      const rows = Array.from(document.querySelectorAll(`#${itemsTbodyId} .item-row`));
      const items = rows.map(r => ({
        qty: r.querySelector('input[name="qty[]"]')?.value || "",
        desc: r.querySelector('textarea[name="desc[]"]')?.value || "",
        material: r.querySelector('input[name="material[]"]')?.value || "",
        notes: r.querySelector('textarea[name="notes[]"]')?.value || ""
      })).filter(it => it.qty || it.desc || it.material || it.notes);

      fd.append("order_type", form.id === 'quickOrderForm' ? 'quick' : 'large');
      fd.set("items_json", JSON.stringify(items));

      const res = await fetch("/api/orders", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data.ok) {
        const msg = data.error || data.message || `Request failed (${res.status})`;
        window.location.href = `/order-status.html?ok=0&msg=${encodeURIComponent(msg)}`;
        return;
      }

      if (form && typeof form.reset === "function") form.reset();

      const orderId = data.order_id || "";
      const jobId = data.job_id || "";
      window.location.href =
        `/order-status.html?ok=1&order_id=${encodeURIComponent(orderId)}&job_id=${encodeURIComponent(jobId)}`;

    } catch (err) {
      window.location.href = `/order-status.html?ok=0&msg=${encodeURIComponent(err?.message || "Network error")}`;
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = btn.dataset._text || "Submit"; }
    }
  }

  // Hook up forms (update IDs if different)
  const quickForm = document.getElementById("quickOrderForm");
  const largeForm = document.getElementById("largeOrderForm");
  if (quickForm) {
    const errors = document.getElementById("formErrorsQuick");
    quickForm.addEventListener("submit", (e) => { e.preventDefault(); submitOrder(quickForm, errors); });
  }
  if (largeForm) {
    const errors = document.getElementById("formErrorsLarge");
    largeForm.addEventListener("submit", (e) => { e.preventDefault(); submitOrder(largeForm, errors); });
  }
})();

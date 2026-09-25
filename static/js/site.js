(function () {
  "use strict";

  var nav = document.querySelector(".site-nav, .navbar.sticky-top");
  if (nav) {
    var onScroll = function () {
      nav.classList.toggle("is-scrolled", window.scrollY > 24);
      nav.style.top = "0px";
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  var params = new URLSearchParams(window.location.search);
  var requestedCover = params.get("cover");

  function setCover(select, cover) {
    if (!select || !cover) return;
    var match = Array.prototype.find.call(select.options, function (option) {
      return option.value === cover || option.text === cover;
    });
    if (match) {
      select.value = match.value || match.text;
    }
  }

  if (requestedCover) {
    document.querySelectorAll("#insuranceType, [name='insuranceType']").forEach(function (select) {
      setCover(select, requestedCover);
    });
  }

  function fieldValue(form, id) {
    var el = form.querySelector("[name='" + id + "']") || form.querySelector("#" + id) || document.getElementById(id);
    return el ? String(el.value || "").trim() : "";
  }

  function coverSelect(form) {
    return form.querySelector("[name='insuranceType']") || form.querySelector("#insuranceType");
  }

  var quoteModalEl = document.getElementById("quoteModal");
  var quoteForm = quoteModalEl ? quoteModalEl.querySelector("[data-quote-form]") : null;
  var quoteLabel = quoteModalEl ? quoteModalEl.querySelector("[data-quote-cover-label]") : null;
  var quoteModal = null;
  var quoteBackdrop = null;

  function prepareQuoteForm(cover) {
    if (quoteForm) {
      quoteForm.reset();
      var status = quoteForm.querySelector("[data-form-status]");
      if (status) status.textContent = "";
      quoteForm.setAttribute("data-selected-cover", cover || "");
      setCover(coverSelect(quoteForm), cover);
    }
    if (quoteLabel) {
      if (cover) {
        quoteLabel.hidden = false;
        quoteLabel.textContent = cover;
      } else {
        quoteLabel.hidden = true;
        quoteLabel.textContent = "";
      }
    }
  }

  function closeQuoteModal() {
    if (quoteModal && quoteModal.hide) {
      quoteModal.hide();
      return;
    }
    if (!quoteModalEl) return;
    quoteModalEl.classList.remove("show");
    quoteModalEl.style.display = "none";
    quoteModalEl.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("overflow");
    document.body.style.removeProperty("padding-right");
    if (quoteBackdrop) {
      quoteBackdrop.remove();
      quoteBackdrop = null;
    }
  }

  function showQuoteFallback() {
    if (!quoteModalEl) return;
    quoteModalEl.classList.add("show");
    quoteModalEl.style.display = "block";
    quoteModalEl.removeAttribute("aria-hidden");
    document.body.classList.add("modal-open");
    document.body.style.overflow = "hidden";
    if (!quoteBackdrop) {
      quoteBackdrop = document.createElement("div");
      quoteBackdrop.className = "modal-backdrop fade show";
      quoteBackdrop.addEventListener("click", closeQuoteModal);
      document.body.appendChild(quoteBackdrop);
    }
  }

  function getQuoteModal() {
    if (quoteModal) return quoteModal;
    if (!quoteModalEl || !window.bootstrap || !window.bootstrap.Modal) return null;
    try {
      if (window.bootstrap.Modal.getInstance) {
        quoteModal = window.bootstrap.Modal.getInstance(quoteModalEl);
      }
      if (!quoteModal) {
        quoteModal = new window.bootstrap.Modal(quoteModalEl);
      }
      return quoteModal;
    } catch (err) {
      quoteModal = null;
      return null;
    }
  }

  function openQuoteModal(cover) {
    prepareQuoteForm(cover);
    var instance = getQuoteModal();
    if (instance) {
      instance.show();
      return;
    }
    showQuoteFallback();
  }

  if (quoteModalEl) {
    quoteModalEl.addEventListener("show.bs.modal", function (event) {
      var trigger = event.relatedTarget;
      prepareQuoteForm(trigger ? trigger.getAttribute("data-quote-cover") || "" : quoteForm ? quoteForm.getAttribute("data-selected-cover") : "");
    });
    quoteModalEl.querySelectorAll("[data-bs-dismiss='modal']").forEach(function (btn) {
      btn.addEventListener("click", closeQuoteModal);
    });
  }

  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-quote-open]");
    if (!btn) return;
    event.preventDefault();
    openQuoteModal(btn.getAttribute("data-quote-cover") || "");
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && quoteModalEl && quoteModalEl.classList.contains("show")) {
      closeQuoteModal();
    }
  });

  function showFormStatus(form, message, ok) {
    var box = form.querySelector("[data-form-status]");
    if (!box) {
      box = document.createElement("p");
      box.setAttribute("data-form-status", "");
      box.className = "mt-3 mb-0";
      form.appendChild(box);
    }
    box.textContent = message;
    box.style.color = ok ? "#0e7a43" : "#b42318";
  }

  document.querySelectorAll("[data-amiri-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = form.querySelector('button[type="submit"]');
      var payload = {
        name: fieldValue(form, "gname") || fieldValue(form, "name"),
        email: fieldValue(form, "gmail") || fieldValue(form, "email"),
        mobile: fieldValue(form, "cname") || fieldValue(form, "mobile") || fieldValue(form, "phone"),
        cover: fieldValue(form, "insuranceType") || fieldValue(form, "cover") || "Other",
        message: fieldValue(form, "message") || fieldValue(form, "subject"),
        prefDate: fieldValue(form, "prefDate"),
        prefTime: fieldValue(form, "prefTime"),
        website: fieldValue(form, "website"),
        source: window.location.pathname.split("/").pop() || "website"
      };
      if (button) {
        button.disabled = true;
      }
      fetch("/api/form-token")
        .then(function (res) { return res.json(); })
        .then(function (tokenData) {
          payload.formToken = tokenData.token;
          return fetch("/api/requests", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          });
        })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok && result.data.success) {
            showFormStatus(form, result.data.message || "We received your request.", true);
            var keepCover = form.getAttribute("data-selected-cover") || requestedCover;
            form.reset();
            setCover(coverSelect(form), keepCover);
            return;
          }
          var errors = (result.data && result.data.errors) || [];
          showFormStatus(form, errors.join(" ") || (result.data && result.data.message) || "Please check the form.", false);
        })
        .catch(function () {
          showFormStatus(form, "Could not send the request. Check your connection and try again.", false);
        })
        .finally(function () {
          if (button) button.disabled = false;
        });
    });
  });

  document.querySelectorAll("#mc-embedded-subscribe-form").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var input = form.querySelector("input[type='email']");
      var response = document.getElementById("responseMessage");
      var email = input ? input.value.trim() : "";
      fetch("/api/form-token")
        .then(function (res) { return res.json(); })
        .then(function (tokenData) {
          return fetch("/api/subscribers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email, website: "", formToken: tokenData.token })
          });
        })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (response) {
            response.textContent = data.message || "Thank you for subscribing.";
            response.style.color = data.success ? "#f3c453" : "#ffb4a8";
          }
          if (data.success && input) input.value = "";
        })
        .catch(function () {
          if (response) {
            response.textContent = "Could not subscribe just now. Please try again.";
            response.style.color = "#ffb4a8";
          }
        });
    });
  });

  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = new Date().getFullYear();
  });
})();

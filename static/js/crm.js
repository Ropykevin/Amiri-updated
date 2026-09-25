(function () {
  "use strict";

  var staff = [];
  var leads = [];
  var accounts = [];
  var deals = [];
  var dash = null;
  var pieChart = null;
  var barChart = null;
  var topChart = null;
  var yearlyChart = null;
  var invoices = [];
  var payTo = null;
  var current = { kind: "lead", record: null };

  var FILE_LABELS = {
    quotation: "Quotation",
    logbook: "Logbook",
    pin: "KRA PIN",
    national_id: "National ID",
    cert_incorporation: "Certificate of incorporation",
    cheque: "Cheque",
    valuation: "Valuation report"
  };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function kes(n) {
    return "KES " + Number(n || 0).toLocaleString("en-KE", { maximumFractionDigits: 0 });
  }

  function api(url, options) {
    return fetch(url, Object.assign({ credentials: "same-origin", cache: "no-store" }, options || {})).then(function (res) {
      if (res.status === 401) {
        window.location.href = "/admin/login?next=/admin";
        throw new Error("Please sign in.");
      }
      return res.json().then(function (data) {
        if (!res.ok) throw new Error((data && data.message) || "Request failed");
        return data;
      });
    });
  }

  function detailsFromForm() {
    var service = document.getElementById("crmService").value;
    var clientType = document.getElementById("crmClientType").value;
    var details = {};
    if (service === "medical") {
      details.limits = {
        inpatient: document.getElementById("limIn").value,
        outpatient: document.getElementById("limOut").value,
        dental: document.getElementById("limDental").value,
        optical: document.getElementById("limOptical").value,
        maternity: document.getElementById("limMaternity").value
      };
      if (clientType === "individual") details.dob = document.getElementById("crmDob").value;
      else {
        details.population = document.getElementById("crmMedPop").value;
        details.category = document.getElementById("crmCategory").value;
      }
    }
    if (service === "wiba") {
      details.population = document.getElementById("crmWibaPop").value;
      details.cover_amount = document.getElementById("crmWibaAmount").value;
    }
    details.premium = document.getElementById("crmPremium").value;
    if (service === "motor") {
      details.vehicle = {
        registration: document.getElementById("vehReg").value,
        make: document.getElementById("vehMake").value,
        model: document.getElementById("vehModel").value,
        year: document.getElementById("vehYear").value,
        chassis: document.getElementById("vehChassis").value,
        value: document.getElementById("vehValue").value
      };
      details.installment = document.getElementById("crmInstallment").checked;
      details.premium = document.getElementById("crmPremium").value;
    }
    return details;
  }

  function fillDetails(details) {
    details = details || {};
    var limits = details.limits || {};
    var vehicle = details.vehicle || {};
    document.getElementById("limIn").value = limits.inpatient || "";
    document.getElementById("limOut").value = limits.outpatient || "";
    document.getElementById("limDental").value = limits.dental || "";
    document.getElementById("limOptical").value = limits.optical || "";
    document.getElementById("limMaternity").value = limits.maternity || "";
    document.getElementById("crmDob").value = details.dob || "";
    document.getElementById("crmMedPop").value = details.population || "";
    document.getElementById("crmCategory").value = details.category === "B" ? "B" : "A";
    document.getElementById("crmWibaPop").value = details.population || "";
    document.getElementById("crmWibaAmount").value = details.cover_amount || "";
    document.getElementById("vehReg").value = vehicle.registration || "";
    document.getElementById("vehMake").value = vehicle.make || "";
    document.getElementById("vehModel").value = vehicle.model || "";
    document.getElementById("vehYear").value = vehicle.year || "";
    document.getElementById("vehChassis").value = vehicle.chassis || "";
    document.getElementById("vehValue").value = vehicle.value || "";
    document.getElementById("crmInstallment").checked = !!details.installment;
    if (details.premium) document.getElementById("crmPremium").value = details.premium;
  }

  function toggleFields() {
    var service = document.getElementById("crmService").value;
    var type = document.getElementById("crmClientType").value;
    var kind = document.getElementById("crmKind").value;
    document.querySelectorAll(".crm-medical, .crm-wiba, .crm-motor, .crm-deal-only").forEach(function (el) {
      el.style.display = "none";
    });
    document.querySelectorAll(".crm-" + service).forEach(function (el) {
      var isInd = el.classList.contains("crm-individual");
      var isCorp = el.classList.contains("crm-corporate");
      if (isInd && type !== "individual") el.style.display = "none";
      else if (isCorp && type !== "corporate") el.style.display = "none";
      else el.style.display = "";
    });
    if (kind === "deal") {
      document.querySelectorAll(".crm-deal-only").forEach(function (el) { el.style.display = ""; });
    }
    document.getElementById("crmStatusWrap").style.display = kind === "lead" ? "" : "none";
    var status = document.getElementById("crmStatus").value;
    var showFiles = kind === "deal" || (kind === "lead" && status !== "new" && document.getElementById("crmId").value);
    document.getElementById("crmFilesWrap").style.display = showFiles ? "" : "none";
    document.getElementById("crmPayWrap").style.display = kind === "deal" ? "" : "none";
    fillFileKinds();
  }

  function neededKinds() {
    var service = document.getElementById("crmService").value;
    var type = document.getElementById("crmClientType").value;
    var kind = document.getElementById("crmKind").value;
    var status = document.getElementById("crmStatus").value;
    var list = [];
    if (kind === "lead" && (status === "contacted" || status === "quoted")) list.push("quotation");
    if (kind === "deal") {
      list.push("quotation", "pin");
      if (type === "corporate") list.push("cert_incorporation");
      if (type === "individual") list.push("national_id");
      list.push("cheque");
      if (service === "motor") list.push("logbook", "valuation", "national_id");
    }
    var unique = [];
    list.forEach(function (item) {
      if (unique.indexOf(item) === -1) unique.push(item);
    });
    return unique;
  }

  function fillFileKinds() {
    var select = document.getElementById("crmFileKind");
    select.innerHTML = neededKinds().map(function (kind) {
      return '<option value="' + kind + '">' + esc(FILE_LABELS[kind] || kind) + "</option>";
    }).join("");
    var hint = "Contacted: upload the quotation. Sold: quote, PIN, ID or incorporation, cheque or M-Pesa.";
    if (document.getElementById("crmService").value === "motor") {
      hint = "Motor: logbook, PIN, ID, quote, valuation. Corporate also needs a certificate of incorporation. Uploading a logbook fills registration when the PDF has text.";
    }
    document.getElementById("crmFilesHint").textContent = hint;
  }

  function fillOwner(selected) {
    var select = document.getElementById("crmOwner");
    select.innerHTML = '<option value="">Unassigned</option>' + staff.map(function (user) {
      return '<option value="' + esc(user.id) + '">' + esc(user.name || user.username) + "</option>";
    }).join("");
    select.value = selected || "";
  }

  function renderFiles(files) {
    var box = document.getElementById("crmFileList");
    if (!files || !files.length) {
      box.innerHTML = '<p class="text-muted small mb-0">No documents yet.</p>';
      return;
    }
    box.innerHTML = files.map(function (file) {
      return '<a class="file-chip" href="' + esc(file.url) + '" target="_blank" rel="noopener">' +
        esc(FILE_LABELS[file.kind] || file.kind) + " · " + esc(file.name) + "</a>";
    }).join("");
  }

  function renderPayments(payments) {
    var box = document.getElementById("crmPayList");
    if (!payments || !payments.length) {
      box.innerHTML = '<p class="text-muted small mb-0">No payments yet. Revenue counts when you add M-Pesa or cheque.</p>';
      return;
    }
    box.innerHTML = payments.map(function (pay) {
      return '<div class="d-flex justify-content-between border-bottom py-1"><span>' +
        esc(pay.method) + (pay.mpesaCode ? " · " + esc(pay.mpesaCode) : "") +
        "</span><strong>" + kes(pay.amount) + "</strong></div>";
    }).join("");
  }

  function openLead(lead, isNew) {
    current = { kind: "lead", record: lead };
    document.getElementById("crmKind").value = "lead";
    document.getElementById("crmId").value = (lead && lead.id) || "";
    document.getElementById("crmTitle").textContent = isNew ? "New lead" : (lead.name || "Lead");
    document.getElementById("crmMeta").textContent = isNew ? "Contacted becomes an account. Sold becomes a deal." : (lead.cover || "") + " · " + (lead.createdAt || "");
    document.getElementById("crmName").value = (lead && lead.name) || "";
    document.getElementById("crmEmail").value = (lead && lead.email) || "";
    document.getElementById("crmMobile").value = (lead && lead.mobile) || "";
    document.getElementById("crmPin").value = "";
    document.getElementById("crmService").value = (lead && lead.service) || "medical";
    document.getElementById("crmClientType").value = (lead && lead.clientType) || "individual";
    document.getElementById("crmStatus").value = (lead && lead.status) || "new";
    document.getElementById("crmNotes").value = (lead && lead.notes) || "";
    document.getElementById("crmPremium").value = "";
    fillOwner(lead && lead.ownerId);
    fillDetails(lead && lead.details);
    renderFiles(lead && lead.files);
    toggleFields();
    new bootstrap.Modal(document.getElementById("crmModal")).show();
  }

  function openDeal(deal) {
    current = { kind: "deal", record: deal };
    document.getElementById("crmKind").value = "deal";
    document.getElementById("crmId").value = deal.id;
    document.getElementById("crmTitle").textContent = deal.accountName || "Deal";
    document.getElementById("crmMeta").textContent = deal.cover + " · paid " + kes(deal.paid);
    document.getElementById("crmName").value = deal.accountName || "";
    document.getElementById("crmEmail").value = deal.accountEmail || "";
    document.getElementById("crmMobile").value = deal.accountMobile || "";
    document.getElementById("crmPin").value = "";
    document.getElementById("crmService").value = deal.service || "medical";
    document.getElementById("crmClientType").value = deal.clientType || "individual";
    document.getElementById("crmInsurer").value = deal.insurer || "";
    document.getElementById("crmPremium").value = deal.premium || "";
    document.getElementById("crmInception").value = deal.inceptionDate || "";
    document.getElementById("crmExpiry").value = deal.expiryDate || "";
    document.getElementById("crmNotes").value = "";
    fillOwner(deal.ownerId);
    fillDetails(deal.details);
    document.getElementById("crmInstallment").checked = !!deal.installment;
    if (deal.vehicleValue && !document.getElementById("vehValue").value) {
      document.getElementById("vehValue").value = deal.vehicleValue;
    }
    renderFiles(deal.files);
    renderPayments(deal.payments);
    toggleFields();
    new bootstrap.Modal(document.getElementById("crmModal")).show();
  }

  function hideModal() {
    var el = document.getElementById("crmModal");
    var inst = bootstrap.Modal.getInstance(el);
    if (!inst) inst = new bootstrap.Modal(el);
    inst.hide();
    document.querySelectorAll(".modal-backdrop").forEach(function (node) { node.remove(); });
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("padding-right");
  }

  function showCrmTab(name) {
    var btn = document.querySelector('.admin-nav button[data-tab="' + name + '"]');
    if (btn) btn.click();
  }

  function saveRecord() {
    var btn = document.getElementById("crmSave");
    var kind = document.getElementById("crmKind").value;
    var id = document.getElementById("crmId").value;
    var payload = {
      name: document.getElementById("crmName").value,
      email: document.getElementById("crmEmail").value,
      mobile: document.getElementById("crmMobile").value,
      service: document.getElementById("crmService").value,
      clientType: document.getElementById("crmClientType").value,
      ownerId: document.getElementById("crmOwner").value,
      notes: document.getElementById("crmNotes").value,
      details: detailsFromForm(),
      kraPin: document.getElementById("crmPin").value,
      dob: document.getElementById("crmDob").value
    };
    var url;
    var method;
    if (kind === "lead" && !id) {
      url = "/api/admin/crm/leads";
      method = "POST";
    } else if (kind === "lead") {
      payload.status = document.getElementById("crmStatus").value;
      url = "/api/admin/crm/leads/" + id;
      method = "PATCH";
    } else {
      payload.insurer = document.getElementById("crmInsurer").value;
      payload.premium = document.getElementById("crmPremium").value;
      payload.vehicleValue = document.getElementById("vehValue").value;
      payload.inceptionDate = document.getElementById("crmInception").value;
      payload.expiryDate = document.getElementById("crmExpiry").value;
      payload.installment = document.getElementById("crmInstallment").checked;
      url = "/api/admin/crm/deals/" + id;
      method = "PATCH";
    }
    btn.disabled = true;
    btn.textContent = "Saving…";
    api(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (data) {
      var record = data.lead || data.deal;
      if (!record) throw new Error((data && data.message) || "Save failed");
      current.record = record;
      return load().then(function () { return record; });
    }).then(function (record) {
      hideModal();
      if (kind === "deal" || (record && record.status === "won")) showCrmTab("deals");
      else showCrmTab("leads");
    }).catch(function (err) {
      alert(err.message || "Could not save.");
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Save";
    });
  }

  function uploadFile() {
    var id = document.getElementById("crmId").value;
    var kind = document.getElementById("crmKind").value;
    var input = document.getElementById("crmFileInput");
    if (!id) {
      alert("Save the record first, then upload.");
      return;
    }
    if (!input.files || !input.files[0]) {
      alert("Choose a file.");
      return;
    }
    var form = new FormData();
    form.append("file", input.files[0]);
    form.append("kind", document.getElementById("crmFileKind").value);
    if (kind === "lead") form.append("leadId", id);
    if (kind === "deal") form.append("dealId", id);
    fetch("/api/admin/crm/files", { method: "POST", credentials: "same-origin", body: form })
      .then(function (res) { return res.json().then(function (data) { if (!res.ok) throw new Error(data.message || "Upload failed"); return data; }); })
      .then(function (data) {
        input.value = "";
        if (data.extracted && data.extracted.registration) {
          document.getElementById("vehReg").value = data.extracted.registration || document.getElementById("vehReg").value;
          document.getElementById("vehYear").value = data.extracted.year || document.getElementById("vehYear").value;
          document.getElementById("vehChassis").value = data.extracted.chassis || document.getElementById("vehChassis").value;
        }
        var path = kind === "lead" ? "/api/admin/crm/leads/" + id : "/api/admin/crm/deals/" + id;
        return api(path);
      })
      .then(function (record) {
        current.record = record;
        renderFiles(record.files || []);
        if (record.details) fillDetails(record.details);
        return load();
      })
      .catch(function (err) { alert(err.message); });
  }

  function addPayment() {
    var id = document.getElementById("crmId").value;
    api("/api/admin/crm/deals/" + id + "/payments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        method: document.getElementById("payMethod").value,
        mpesaCode: document.getElementById("payCode").value,
        amount: document.getElementById("payAmount").value
      })
    }).then(function (data) {
      document.getElementById("payCode").value = "";
      document.getElementById("payAmount").value = "";
      current.record = data.deal;
      renderPayments(data.deal.payments);
      return load();
    }).catch(function (err) { alert(err.message); });
  }

  function monthLabel(key) {
    var parts = String(key || "").split("-");
    if (parts.length < 2) return key || "";
    var names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var month = Number(parts[1]) - 1;
    return (names[month] || parts[1]) + " " + String(parts[0]).slice(2);
  }

  function palette() {
    return ["#1572B7", "#F19729", "#0b4a73", "#ffc56a", "#0f5a91", "#d67d1c", "#c5e0f2"];
  }

  function resetChart(existing, canvas) {
    if (window.Chart) {
      Chart.defaults.color = "#0b4a73";
      Chart.defaults.borderColor = "rgba(21, 114, 183, 0.18)";
    }
    if (existing) existing.destroy();
    if (canvas && window.Chart) {
      var old = Chart.getChart(canvas);
      if (old) old.destroy();
    }
  }

  function payToHtml(info) {
    info = info || payTo || {};
    return '<div class="pay-to-card">' +
      "<strong>Payment details</strong>" +
      '<div class="pay-to-name">' + esc(info.accountName || "AMIRI INSURANCE AGENCY") + "</div>" +
      "<div>" + esc(info.bank || "KCB Bank") + " · Account " + esc(info.accountNumber || "1272842827") + "</div></div>";
  }

  function renderDashboard() {
    if (!dash) return;
    var target = dash.target || 10000;
    var percent = dash.percent != null ? dash.percent : 0;
    var targetEl = document.getElementById("statTarget");
    if (targetEl) targetEl.textContent = kes(target);
    document.getElementById("statMonthRevenue").textContent = kes(dash.monthlyRevenue);
    var clientsEl = document.getElementById("statClients");
    if (clientsEl) clientsEl.textContent = String(dash.clientCount || 0);
    var pctEl = document.getElementById("statPercent");
    if (pctEl) pctEl.textContent = percent + "%";
    var bench = document.getElementById("statBenchmark");
    if (bench) bench.textContent = Number(target).toLocaleString("en-KE");
    var targetInput = document.getElementById("targetInput");
    if (targetInput) targetInput.placeholder = String(Math.round(target));
    var renewals = document.getElementById("renewalsList");
    if (!dash.renewals.length) {
      renewals.innerHTML = '<p class="text-muted mb-0">No renewals in the next 30 days.</p>';
    } else {
      renewals.innerHTML = dash.renewals.map(function (row) {
        return '<div class="d-flex justify-content-between align-items-center py-2 border-bottom">' +
          "<div><strong>" + esc(row.name) + "</strong><br><small>" + esc(row.cover) + " · due " + esc(row.dueDate) +
          (row.noticeSentAt ? " · notice sent" : "") + "</small></div>" +
          '<button class="btn btn-sm btn-outline-primary" data-open-deal="' + esc(row.dealId) + '">Open</button></div>';
      }).join("");
    }
    var pieEl = document.getElementById("staffPie");
    var barEl = document.getElementById("monthBars");
    var topEl = document.getElementById("monthlyTop");
    var yearEl = document.getElementById("yearlyPct");
    var staffRows = dash.staffRevenue || [];
    var yearlyRows = dash.yearlyStaff || [];
    var series = dash.monthlySeries || [];
    try {
      if (window.Chart && pieEl) {
        resetChart(pieChart, pieEl);
        pieChart = new Chart(pieEl, {
          type: "pie",
          data: {
            labels: staffRows.length ? staffRows.map(function (row) { return row.name; }) : ["No revenue"],
            datasets: [{
              data: staffRows.length ? staffRows.map(function (row) { return row.revenue; }) : [1],
              backgroundColor: palette()
            }]
          },
          options: { plugins: { legend: { position: "bottom" } } }
        });
      }
      if (window.Chart && barEl) {
        resetChart(barChart, barEl);
        barChart = new Chart(barEl, {
          type: "bar",
          data: {
            labels: series.map(function (row) { return monthLabel(row.month); }),
            datasets: [
              {
                type: "bar",
                label: "Revenue",
                data: series.map(function (row) { return row.revenue; }),
                backgroundColor: "#1572B7"
              },
              {
                type: "line",
                label: "Target",
                data: series.map(function () { return target; }),
                borderColor: "#F19729",
                backgroundColor: "#F19729",
                borderWidth: 2,
                pointRadius: 0,
                tension: 0
              }
            ]
          },
          options: { plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true } } }
        });
      }
      if (window.Chart && topEl) {
        resetChart(topChart, topEl);
        topChart = new Chart(topEl, {
          type: "bar",
          data: {
            labels: staffRows.length ? staffRows.map(function (row) { return row.name; }) : ["No revenue"],
            datasets: [{
              label: "This month",
              data: staffRows.length ? staffRows.map(function (row) { return row.revenue; }) : [0],
              backgroundColor: "#F19729"
            }]
          },
          options: {
            indexAxis: "y",
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true } }
          }
        });
      }
      if (window.Chart && yearEl) {
        resetChart(yearlyChart, yearEl);
        yearlyChart = new Chart(yearEl, {
          type: "doughnut",
          data: {
            labels: yearlyRows.length ? yearlyRows.map(function (row) { return row.name + " " + row.percent + "%"; }) : ["No yearly revenue"],
            datasets: [{
              data: yearlyRows.length ? yearlyRows.map(function (row) { return row.percent || row.revenue; }) : [1],
              backgroundColor: palette()
            }]
          },
          options: { plugins: { legend: { position: "bottom" } } }
        });
      }
    } catch (err) {
      console.warn("CRM charts", err);
    }
  }

  function renderInvoices() {
    var box = document.getElementById("invoicePayTo");
    if (box) box.innerHTML = payToHtml(payTo);
    var searchEl = document.getElementById("invoiceSearch");
    var statusEl = document.getElementById("invoiceStatus");
    if (!searchEl || !statusEl) return;
    var q = (searchEl.value || "").toLowerCase();
    var status = statusEl.value;
    var rows = invoices.filter(function (row) {
      var hay = [row.number, row.clientName, row.clientEmail, row.clientMobile, row.cover, row.description].join(" ").toLowerCase();
      return (!q || hay.indexOf(q) !== -1) && (status === "all" || row.status === status);
    });
    document.getElementById("invoicesEmpty").style.display = rows.length ? "none" : "block";
    document.getElementById("invoicesBody").innerHTML = rows.map(function (row) {
      return "<tr><td><strong>" + esc(row.number) + "</strong></td><td>" + esc(row.clientName) +
        "</td><td>" + esc(row.cover) + "</td><td>" + kes(row.amount) +
        "</td><td>" + esc(row.dueDate || "—") +
        '</td><td><span class="status-pill status-' + esc(row.status) + '">' + esc(row.status) +
        '</span></td><td class="text-nowrap"><button class="btn btn-sm btn-outline-primary" data-open-invoice="' +
        esc(row.id) + '">Edit</button> <button class="btn btn-sm btn-outline-primary" data-email-invoice="' +
        esc(row.id) + '">Email</button> <a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" href="/admin/invoices/' +
        esc(row.id) + '">Print</a></td></tr>';
    }).join("");
  }

  function fillInvoiceAccounts(selected) {
    var select = document.getElementById("invAccount");
    if (!select) return;
    select.innerHTML = '<option value="">Walk-in / new client</option>' + accounts.map(function (row) {
      return '<option value="' + esc(row.id) + '">' + esc(row.name) + "</option>";
    }).join("");
    select.value = selected || "";
  }

  function hideInvoiceModal() {
    var el = document.getElementById("invoiceModal");
    if (!el) return;
    var inst = bootstrap.Modal.getInstance(el);
    if (!inst) inst = new bootstrap.Modal(el);
    inst.hide();
    document.querySelectorAll(".modal-backdrop").forEach(function (node) { node.remove(); });
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("padding-right");
  }

  function openInvoice(invoice, isNew) {
    fillInvoiceAccounts(invoice && invoice.accountId);
    document.getElementById("invId").value = (invoice && invoice.id) || "";
    document.getElementById("invTitle").textContent = isNew ? "New invoice" : ((invoice && invoice.number) || "Invoice");
    document.getElementById("invMeta").textContent = isNew ? "KCB account details are added automatically." : ((invoice && invoice.createdAt) || "");
    document.getElementById("invName").value = (invoice && invoice.clientName) || "";
    document.getElementById("invEmail").value = (invoice && invoice.clientEmail) || "";
    document.getElementById("invMobile").value = (invoice && invoice.clientMobile) || "";
    document.getElementById("invClientType").value = (invoice && invoice.clientType) || "individual";
    document.getElementById("invService").value = (invoice && invoice.service) || "medical";
    document.getElementById("invDescription").value = (invoice && invoice.description) || "";
    document.getElementById("invAmount").value = invoice && invoice.amount ? invoice.amount : "";
    document.getElementById("invDue").value = (invoice && invoice.dueDate) || "";
    document.getElementById("invNotes").value = (invoice && invoice.notes) || "";
    document.getElementById("invStatus").value = (invoice && invoice.status) || "unpaid";
    document.getElementById("invPayPreview").innerHTML = payToHtml((invoice && invoice.payTo) || payTo);
    var emailBtn = document.getElementById("invEmailBtn");
    if (emailBtn) emailBtn.style.display = isNew || !(invoice && invoice.id) ? "none" : "";
    new bootstrap.Modal(document.getElementById("invoiceModal")).show();
  }

  function emailInvoice(id, email) {
    var invoice = invoices.find(function (row) { return row.id === id; });
    var dest = (email || (invoice && invoice.clientEmail) || "").trim();
    if (!dest) {
      alert("Add a client email, then send the invoice.");
      if (invoice) openInvoice(invoice, false);
      return;
    }
    var label = invoice && invoice.number ? invoice.number : "this invoice";
    if (!confirm("Send " + label + " to " + dest + "?")) return;
    api("/api/admin/crm/invoices/" + id + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clientEmail: dest })
    }).then(function (data) {
      alert(data.message || "Invoice emailed.");
    }).catch(function (err) {
      alert(err.message || "Could not send the invoice.");
    });
  }

  function emailCurrentInvoice() {
    var id = document.getElementById("invId").value;
    if (!id) {
      alert("Save the invoice first, then email it.");
      return;
    }
    emailInvoice(id, document.getElementById("invEmail").value);
  }

  function saveInvoice() {
    var btn = document.getElementById("invSave");
    var id = document.getElementById("invId").value;
    var payload = {
      clientName: document.getElementById("invName").value,
      clientEmail: document.getElementById("invEmail").value,
      clientMobile: document.getElementById("invMobile").value,
      clientType: document.getElementById("invClientType").value,
      service: document.getElementById("invService").value,
      description: document.getElementById("invDescription").value,
      amount: document.getElementById("invAmount").value,
      dueDate: document.getElementById("invDue").value,
      notes: document.getElementById("invNotes").value,
      status: document.getElementById("invStatus").value,
      accountId: document.getElementById("invAccount").value || null
    };
    btn.disabled = true;
    btn.textContent = "Saving…";
    api(id ? "/api/admin/crm/invoices/" + id : "/api/admin/crm/invoices", {
      method: id ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (data) {
      if (!data.invoice) throw new Error((data && data.message) || "Save failed");
      return load().then(function () { return data.invoice; });
    }).then(function () {
      hideInvoiceModal();
      showCrmTab("invoices");
    }).catch(function (err) {
      alert(err.message || "Could not save invoice.");
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Save invoice";
    });
  }

  function renderLeads() {
    var q = (document.getElementById("leadSearch").value || "").toLowerCase();
    var status = document.getElementById("leadStatus").value;
    var service = document.getElementById("leadService").value;
    var rows = leads.filter(function (row) {
      var hay = [row.name, row.email, row.mobile, row.cover, row.ownerName].join(" ").toLowerCase();
      return (!q || hay.indexOf(q) !== -1) &&
        (status === "all" || row.status === status) &&
        (service === "all" || row.service === service);
    });
    document.getElementById("leadsEmpty").style.display = rows.length ? "none" : "block";
    document.getElementById("leadsBody").innerHTML = rows.map(function (row) {
      return "<tr><td><strong>" + esc(row.name) + "</strong><br><small>" + esc(row.email || row.mobile || "") +
        "</small></td><td>" + esc(row.cover) + "</td><td>" + esc(row.clientType) +
        "</td><td>" + esc(row.ownerName || "—") +
        '</td><td><span class="status-pill status-' + esc(row.status) + '">' + esc(row.status) +
        '</span></td><td><button class="btn btn-sm btn-outline-primary" data-open-lead="' + esc(row.id) +
        '">Open</button></td></tr>';
    }).join("");
  }

  function renderAccounts() {
    var q = (document.getElementById("accountSearch").value || "").toLowerCase();
    var rows = accounts.filter(function (row) {
      return !q || [row.name, row.email, row.mobile, row.kraPin].join(" ").toLowerCase().indexOf(q) !== -1;
    });
    document.getElementById("accountsEmpty").style.display = rows.length ? "none" : "block";
    document.getElementById("accountsBody").innerHTML = rows.map(function (row) {
      return "<tr><td><strong>" + esc(row.name) + "</strong><br><small>" + esc(row.email || "") +
        "</small></td><td>" + esc(row.clientType) + "</td><td>" + esc(row.mobile || "—") +
        "</td><td>" + esc(row.kraPin || "—") + "</td><td>" + row.deals +
        '</td><td><button class="btn btn-sm btn-outline-primary" data-open-account="' + esc(row.id) +
        '">View</button></td></tr>';
    }).join("");
  }

  function renderDeals() {
    var q = (document.getElementById("dealSearch").value || "").toLowerCase();
    var service = document.getElementById("dealService").value;
    var rows = deals.filter(function (row) {
      var hay = [row.accountName, row.accountEmail, row.cover, row.ownerName].join(" ").toLowerCase();
      return (!q || hay.indexOf(q) !== -1) && (service === "all" || row.service === service);
    });
    document.getElementById("dealsEmpty").style.display = rows.length ? "none" : "block";
    document.getElementById("dealsBody").innerHTML = rows.map(function (row) {
      return "<tr><td><strong>" + esc(row.accountName) + "</strong></td><td>" + esc(row.cover) +
        "</td><td>" + kes(row.premium) + "</td><td>" + kes(row.paid) +
        "</td><td>" + esc(row.expiryDate || "—") + "</td><td>" + esc(row.ownerName || "—") +
        '</td><td><button class="btn btn-sm btn-outline-primary" data-open-deal="' + esc(row.id) +
        '">Open</button></td></tr>';
    }).join("");
  }

  function load() {
    return Promise.all([
      api("/api/admin/staff").catch(function () { return []; }),
      api("/api/admin/crm/dashboard").catch(function () { return dash || {}; }),
      api("/api/admin/crm/leads"),
      api("/api/admin/crm/accounts").catch(function () { return accounts; }),
      api("/api/admin/crm/deals").catch(function () { return deals; }),
      api("/api/admin/crm/invoices").catch(function () { return { invoices: invoices, payTo: payTo }; })
    ]).then(function (results) {
      staff = results[0] || [];
      if (results[1] && results[1].pipeline) dash = results[1];
      leads = results[2] || [];
      accounts = results[3] || [];
      deals = results[4] || [];
      invoices = (results[5] && results[5].invoices) || [];
      payTo = (results[5] && results[5].payTo) || payTo;
      try { renderDashboard(); } catch (err) { console.warn(err); }
      renderLeads();
      renderAccounts();
      renderDeals();
      renderInvoices();
    });
  }

  document.getElementById("crmService").addEventListener("change", toggleFields);
  document.getElementById("crmClientType").addEventListener("change", toggleFields);
  document.getElementById("crmStatus").addEventListener("change", toggleFields);
  document.getElementById("crmSave").addEventListener("click", saveRecord);
  document.getElementById("crmForm").addEventListener("submit", function (event) {
    event.preventDefault();
    saveRecord();
  });
  document.getElementById("crmUploadBtn").addEventListener("click", uploadFile);
  document.getElementById("crmPayBtn").addEventListener("click", addPayment);
  document.getElementById("newLeadBtn").addEventListener("click", function () {
    openLead({ service: "medical", clientType: "individual", status: "new" }, true);
  });
  function startNewInvoice() {
    showCrmTab("invoices");
    openInvoice({ service: "medical", clientType: "individual", status: "unpaid" }, true);
  }
  document.getElementById("newInvoiceBtn").addEventListener("click", startNewInvoice);
  var newInvoiceTabBtn = document.getElementById("newInvoiceTabBtn");
  if (newInvoiceTabBtn) newInvoiceTabBtn.addEventListener("click", startNewInvoice);
  document.getElementById("invSave").addEventListener("click", saveInvoice);
  var invEmailBtn = document.getElementById("invEmailBtn");
  if (invEmailBtn) invEmailBtn.addEventListener("click", emailCurrentInvoice);
  document.getElementById("invoiceForm").addEventListener("submit", function (event) {
    event.preventDefault();
    saveInvoice();
  });
  document.getElementById("invAccount").addEventListener("change", function () {
    var account = accounts.find(function (row) { return row.id === document.getElementById("invAccount").value; });
    if (!account) return;
    document.getElementById("invName").value = account.name || "";
    document.getElementById("invEmail").value = account.email || "";
    document.getElementById("invMobile").value = account.mobile || "";
    document.getElementById("invClientType").value = account.clientType || "individual";
  });
  document.getElementById("targetForm").addEventListener("submit", function (event) {
    event.preventDefault();
    var value = document.getElementById("targetInput").value;
    api("/api/admin/crm/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ monthlyTarget: value })
    }).then(load).catch(function (err) { alert(err.message || "Could not set target."); });
  });
  ["invoiceSearch", "invoiceStatus"].forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", renderInvoices);
    el.addEventListener("change", renderInvoices);
  });
  ["leadSearch", "leadStatus", "leadService"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", renderLeads);
    document.getElementById(id).addEventListener("change", renderLeads);
  });
  document.getElementById("accountSearch").addEventListener("input", renderAccounts);
  document.getElementById("dealSearch").addEventListener("input", renderDeals);
  document.getElementById("dealService").addEventListener("change", renderDeals);

  document.body.addEventListener("click", function (event) {
    var leadBtn = event.target.closest("[data-open-lead]");
    var dealBtn = event.target.closest("[data-open-deal]");
    var accountBtn = event.target.closest("[data-open-account]");
    var invoiceBtn = event.target.closest("[data-open-invoice]");
    var emailBtn = event.target.closest("[data-email-invoice]");
    if (leadBtn) {
      var lead = leads.find(function (row) { return row.id === leadBtn.getAttribute("data-open-lead"); });
      if (lead) api("/api/admin/crm/leads/" + lead.id).then(function (row) { openLead(row, false); });
    }
    if (dealBtn) {
      api("/api/admin/crm/deals/" + dealBtn.getAttribute("data-open-deal")).then(openDeal);
    }
    if (accountBtn) {
      var account = accounts.find(function (row) { return row.id === accountBtn.getAttribute("data-open-account"); });
      if (account) {
        var related = leads.filter(function (row) { return row.accountId === account.id; })[0];
        var relatedDeal = deals.filter(function (row) { return row.accountId === account.id; })[0];
        if (relatedDeal) api("/api/admin/crm/deals/" + relatedDeal.id).then(openDeal);
        else if (related) api("/api/admin/crm/leads/" + related.id).then(function (row) { openLead(row, false); });
      }
    }
    if (invoiceBtn) {
      var invoice = invoices.find(function (row) { return row.id === invoiceBtn.getAttribute("data-open-invoice"); });
      if (invoice) openInvoice(invoice, false);
    }
    if (emailBtn) {
      emailInvoice(emailBtn.getAttribute("data-email-invoice"));
    }
  });

  window.AmiriCrm = { load: load };
})();

(function () {
  "use strict";

  var bookings = [];
  var posts = [];
  var subscribers = [];
  var users = [];
  var currentRole = "";
  var currentUserId = "";
  var currentPostId = null;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function waLink(mobile) {
    var digits = String(mobile || "").replace(/\D/g, "");
    return digits ? "https://wa.me/" + digits : "";
  }

  function authHeaders() {
    return { "Content-Type": "application/json" };
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

  function showTab(name) {
    document.querySelectorAll(".admin-section").forEach(function (section) {
      section.classList.toggle("active", section.id === "tab-" + name);
    });
    document.querySelectorAll(".admin-nav button").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === name);
    });
    var titles = {
      overview: ["Dashboard", "Target, revenue, clients, and staff share of the business."],
      leads: ["Leads", "New enquiries. Contacted becomes an account. Sold becomes a deal."],
      accounts: ["Accounts", "Clients created automatically when you contact a lead."],
      deals: ["Deals", "Sold policies, payments, documents, and renewal dates."],
      invoices: ["Invoices", "Create bills, email them, and show KCB account details."],
      content: ["Insights", "Review, publish, and edit blog posts."],
      subscribers: ["Newsletter", "People who asked to hear from Amiri."],
      users: ["Users", "Add people who can sign in and manage the app."]
    };
    var copy = titles[name] || titles.overview;
    document.getElementById("adminTitle").textContent = copy[0];
    document.getElementById("adminLead").textContent = copy[1];
    if (history.replaceState) history.replaceState(null, "", "#" + name);
  }

  function reachButtons(row) {
    var phone = row.mobile ? "tel:+" + String(row.mobile).replace(/\D/g, "") : "";
    var mail = row.email ? "mailto:" + encodeURIComponent(row.email) + "?subject=" + encodeURIComponent("Amiri Insurance — " + (row.cover || "your cover")) : "";
    var wa = waLink(row.mobile);
    return (
      (phone ? '<a class="reach-btn" href="' + phone + '" aria-label="Call"><i class="fa fa-phone"></i></a>' : "") +
      (wa ? '<a class="reach-btn" target="_blank" rel="noopener" href="' + wa + '" aria-label="WhatsApp"><i class="fab fa-whatsapp"></i></a>' : "") +
      (mail ? '<a class="reach-btn" href="' + mail + '" aria-label="Email"><i class="fa fa-envelope"></i></a>' : "")
    );
  }

  function renderOverview(data) {
    document.getElementById("statNew").textContent = data.requests.new;
    document.getElementById("statQuoted").textContent = data.requests.quoted;
    document.getElementById("statWon").textContent = data.requests.won;
    document.getElementById("statPosts").textContent = data.posts.published;
    var recent = document.getElementById("recentBookings");
    if (!data.recentRequests.length) {
      recent.innerHTML = '<p class="text-muted mb-0">No bookings yet. They will appear here when someone requests cover.</p>';
      return;
    }
    recent.innerHTML = data.recentRequests.map(function (row) {
      return (
        '<div class="d-flex justify-content-between align-items-center py-2 border-bottom">' +
        "<div><strong>" + esc(row.name) + "</strong><br><small>" + esc(row.cover) + " · " + esc(row.createdAt) + "</small></div>" +
        '<span class="status-pill status-' + esc(row.status || "new") + '">' + esc(row.status || "new") + "</span>" +
        "</div>"
      );
    }).join("");
  }

  function filteredBookings() {
    var q = (document.getElementById("bookingSearch").value || "").toLowerCase();
    var status = document.getElementById("bookingStatus").value;
    var cover = document.getElementById("bookingCover").value;
    return bookings.filter(function (row) {
      var hay = [row.name, row.email, row.mobile, row.cover, row.message].join(" ").toLowerCase();
      return (!q || hay.indexOf(q) !== -1) &&
        (status === "all" || row.status === status) &&
        (cover === "all" || row.cover === cover);
    });
  }

  function renderBookings() {
    var rows = filteredBookings();
    var tbody = document.getElementById("bookingsBody");
    document.getElementById("bookingsEmpty").style.display = rows.length ? "none" : "block";
    tbody.innerHTML = rows.map(function (row) {
      return (
        "<tr>" +
        "<td><strong>" + esc(row.name) + "</strong><br><small>" + esc(row.email) + "</small></td>" +
        "<td>" + esc(row.cover) + "</td>" +
        "<td>" + esc(row.mobile || "—") + "</td>" +
        "<td>" + esc(row.createdAt || "—") + "</td>" +
        '<td><span class="status-pill status-' + esc(row.status || "new") + '">' + esc(row.status || "new") + "</span></td>" +
        "<td>" + reachButtons(row) + "</td>" +
        '<td><button class="btn btn-sm btn-outline-primary" data-open="' + esc(row.id) + '">Open</button></td>' +
        "</tr>"
      );
    }).join("");
  }

  function uniqueContacts() {
    var map = {};
    bookings.forEach(function (row) {
      var key = (row.email || row.mobile || row.id).toLowerCase();
      if (!map[key]) {
        map[key] = {
          name: row.name,
          email: row.email,
          mobile: row.mobile,
          covers: [],
          count: 0,
          lastAt: row.createdAt
        };
      }
      map[key].count += 1;
      if (row.cover && map[key].covers.indexOf(row.cover) === -1) map[key].covers.push(row.cover);
      if (String(row.createdAt || "") > String(map[key].lastAt || "")) map[key].lastAt = row.createdAt;
    });
    return Object.keys(map).map(function (k) { return map[k]; });
  }

  function renderContacts() {
    var q = (document.getElementById("contactSearch").value || "").toLowerCase();
    var people = uniqueContacts().filter(function (person) {
      return !q || [person.name, person.email, person.mobile].join(" ").toLowerCase().indexOf(q) !== -1;
    });
    document.getElementById("contactsEmpty").style.display = people.length ? "none" : "block";
    document.getElementById("contactsBody").innerHTML = people.map(function (person) {
      return (
        "<tr>" +
        "<td><strong>" + esc(person.name) + "</strong></td>" +
        "<td>" + esc(person.email || "—") + "</td>" +
        "<td>" + esc(person.mobile || "—") + "</td>" +
        "<td>" + esc(person.covers.join(", ") || "—") + "</td>" +
        "<td>" + person.count + "</td>" +
        "<td>" + reachButtons(person) + "</td>" +
        "</tr>"
      );
    }).join("");
  }

  function renderUsers() {
    var tbody = document.getElementById("usersBody");
    if (!tbody) return;
    document.getElementById("usersEmpty").style.display = users.length ? "none" : "block";
    tbody.innerHTML = users.map(function (user) {
      var canDelete = user.id !== currentUserId;
      return (
        "<tr>" +
        "<td><strong>" + esc(user.name || user.username) + "</strong></td>" +
        "<td>" + esc(user.username) + "</td>" +
        "<td>" + esc(user.email || "—") + "</td>" +
        "<td>" + esc(user.role) + "</td>" +
        '<td><span class="status-pill status-' + (user.active ? "won" : "closed") + '">' + (user.active ? "Active" : "Off") + "</span></td>" +
        "<td>" +
        (canDelete ? '<button class="btn btn-sm btn-outline-secondary me-1" data-toggle-user="' + esc(user.id) + '" data-active="' + (user.active ? "0" : "1") + '">' + (user.active ? "Turn off" : "Turn on") + "</button>" : "") +
        (canDelete ? '<button class="btn btn-sm btn-outline-danger" data-delete-user="' + esc(user.id) + '">Remove</button>' : "") +
        "</td>" +
        "</tr>"
      );
    }).join("");
  }

  function renderSubscribers() {
    var tbody = document.getElementById("subscribersBody");
    document.getElementById("subscribersEmpty").style.display = subscribers.length ? "none" : "block";
    tbody.innerHTML = subscribers.map(function (row) {
      return "<tr><td>" + esc(row.email) + "</td><td>" + esc(row.createdAt || "—") + "</td></tr>";
    }).join("");
  }

  function renderPosts() {
    var q = (document.getElementById("postSearch").value || "").toLowerCase();
    var status = document.getElementById("postStatus").value;
    var rows = posts.filter(function (post) {
      return (!q || (post.title + " " + post.author).toLowerCase().indexOf(q) !== -1) &&
        (status === "all" || post.status === status);
    });
    document.getElementById("postsEmpty").style.display = rows.length ? "none" : "block";
    document.getElementById("postsBody").innerHTML = rows.map(function (post) {
      return (
        "<tr>" +
        "<td><strong>" + esc(post.title) + "</strong></td>" +
        "<td>" + esc(post.author) + "</td>" +
        "<td>" + esc(post.category) + "</td>" +
        '<td><span class="status-pill status-' + esc(post.status || "draft") + '">' + esc(post.status || "draft") + "</span></td>" +
        "<td>" + esc(post.publishDate || post.createdAt || "—") + "</td>" +
        '<td><button class="btn btn-sm btn-outline-success me-1" data-publish="' + esc(post.id) + '">Publish</button>' +
        '<button class="btn btn-sm btn-outline-danger" data-delete-post="' + esc(post.id) + '">Delete</button></td>' +
        "</tr>"
      );
    }).join("");
  }

  function openBooking(id) {
    var row = bookings.find(function (item) { return item.id === id; });
    if (!row) return;
    document.getElementById("detailName").textContent = row.name;
    document.getElementById("detailMeta").textContent = (row.cover || "") + " · " + (row.createdAt || "");
    document.getElementById("detailEmail").textContent = row.email || "—";
    document.getElementById("detailMobile").textContent = row.mobile || "—";
    document.getElementById("detailMessage").textContent = row.message || "No extra notes from the client.";
    document.getElementById("detailStatus").value = row.status || "new";
    document.getElementById("detailNotes").value = row.notes || "";
    document.getElementById("detailReach").innerHTML = reachButtons(row);
    document.getElementById("saveBooking").setAttribute("data-id", row.id);
    new bootstrap.Modal(document.getElementById("bookingModal")).show();
  }

  function loadAll() {
    var jobs = [
      api("/api/admin/posts"),
      api("/api/admin/subscribers")
    ];
    if (currentRole !== "manager") {
      jobs.push(api("/api/admin/users").catch(function () { return []; }));
    }
    var crmJob = window.AmiriCrm && window.AmiriCrm.load ? window.AmiriCrm.load() : Promise.resolve();
    return Promise.all([crmJob].concat(jobs)).then(function (results) {
      posts = results[1];
      subscribers = results[2];
      users = results[3] || [];
      renderPosts();
      renderSubscribers();
      renderUsers();
    }).catch(function (err) {
      var banner = document.getElementById("adminError");
      banner.textContent = err.message || "Could not load admin data.";
      banner.style.display = "block";
    });
  }

  document.querySelectorAll(".admin-nav button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      showTab(btn.getAttribute("data-tab"));
    });
  });

  ["bookingSearch", "bookingStatus", "bookingCover"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", renderBookings);
      el.addEventListener("change", renderBookings);
    }
  });
  var contactSearch = document.getElementById("contactSearch");
  if (contactSearch) contactSearch.addEventListener("input", renderContacts);
  document.getElementById("postSearch").addEventListener("input", renderPosts);
  document.getElementById("postStatus").addEventListener("change", renderPosts);

  var bookingsBody = document.getElementById("bookingsBody");
  if (bookingsBody) {
    bookingsBody.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-open]");
      if (btn) openBooking(btn.getAttribute("data-open"));
    });
  }

  var saveBooking = document.getElementById("saveBooking");
  if (saveBooking) {
    saveBooking.addEventListener("click", function () {
    var id = this.getAttribute("data-id");
    api("/api/admin/requests/" + id, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({
        status: document.getElementById("detailStatus").value,
        notes: document.getElementById("detailNotes").value
      })
    }).then(function () {
      bootstrap.Modal.getInstance(document.getElementById("bookingModal")).hide();
      return loadAll();
    }).catch(function (err) {
      alert(err.message);
    });
    });
  }

  document.getElementById("postsBody").addEventListener("click", function (event) {
    var publish = event.target.closest("[data-publish]");
    var remove = event.target.closest("[data-delete-post]");
    if (publish) {
      var post = posts.find(function (item) { return item.id === publish.getAttribute("data-publish"); });
      if (!post) return;
      post.status = "published";
      post.publishDate = new Date().toISOString().slice(0, 10);
      api("/api/admin/posts", { method: "PUT", headers: authHeaders(), body: JSON.stringify(posts) }).then(loadAll);
    }
    if (remove && confirm("Delete this post?")) {
      posts = posts.filter(function (item) { return item.id !== remove.getAttribute("data-delete-post"); });
      api("/api/admin/posts", { method: "PUT", headers: authHeaders(), body: JSON.stringify(posts) }).then(loadAll);
    }
  });

  var userForm = document.getElementById("userForm");
  if (userForm) {
    userForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var status = document.getElementById("userFormStatus");
      api("/api/admin/users", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          name: document.getElementById("userName").value,
          username: document.getElementById("userUsername").value,
          email: document.getElementById("userEmail").value,
          password: document.getElementById("userPassword").value,
          role: document.getElementById("userRole").value
        })
      }).then(function () {
        userForm.reset();
        if (status) {
          status.textContent = "User added. They can sign in now.";
          status.style.color = "#0e7a43";
        }
        return loadAll();
      }).catch(function (err) {
        if (status) {
          status.textContent = err.message || "Could not add user.";
          status.style.color = "#b42318";
        }
      });
    });
  }

  var usersBody = document.getElementById("usersBody");
  if (usersBody) {
    usersBody.addEventListener("click", function (event) {
      var toggle = event.target.closest("[data-toggle-user]");
      var remove = event.target.closest("[data-delete-user]");
      if (toggle) {
        api("/api/admin/users/" + toggle.getAttribute("data-toggle-user"), {
          method: "PATCH",
          headers: authHeaders(),
          body: JSON.stringify({ active: toggle.getAttribute("data-active") === "1" })
        }).then(loadAll).catch(function (err) { alert(err.message); });
      }
      if (remove && confirm("Remove this user?")) {
        api("/api/admin/users/" + remove.getAttribute("data-delete-user"), { method: "DELETE" })
          .then(loadAll)
          .catch(function (err) { alert(err.message); });
      }
    });
  }

  function startAdmin() {
    var usersNav = document.getElementById("usersNav");
    if (usersNav) usersNav.style.display = currentRole === "manager" ? "none" : "";
    var allowed = ["overview", "leads", "accounts", "deals", "invoices", "content", "subscribers"];
    if (currentRole !== "manager") allowed.push("users");
    var initial = (window.location.hash || "#overview").replace("#", "");
    if (initial === "bookings") initial = "leads";
    if (initial === "contacts") initial = "accounts";
    showTab(allowed.indexOf(initial) !== -1 ? initial : "overview");
    loadAll();
  }

  if (typeof syncAdminSessionFromFetch === "function") {
    syncAdminSessionFromFetch().then(function (data) {
      if (data && data.logged_in) {
        currentRole = data.role || "";
        currentUserId = data.user_id || "";
        var name = document.getElementById("adminUser");
        if (name) name.textContent = data.username || "Admin";
      }
      startAdmin();
    });
  } else {
    startAdmin();
  }
})();

/**
 * Client-side session markers for admin UI (mirrors the Flask session).
 * Keys are cleared on logout and synced when visiting admin pages.
 */
(function (global) {
    var PREFIX = "amiri_admin_";
    var KEYS = {
        loggedIn: PREFIX + "logged_in",
        username: PREFIX + "username",
        loginAt: PREFIX + "login_at"
    };

    function setAdminSessionStorage(username) {
        try {
            sessionStorage.setItem(KEYS.loggedIn, "1");
            sessionStorage.setItem(KEYS.username, username || "");
            sessionStorage.setItem(KEYS.loginAt, new Date().toISOString());
        } catch (e) {}
    }

    function clearAdminSessionStorage() {
        try {
            sessionStorage.removeItem(KEYS.loggedIn);
            sessionStorage.removeItem(KEYS.username);
            sessionStorage.removeItem(KEYS.loginAt);
        } catch (e) {}
    }

    function syncAdminSessionFromFetch() {
        return fetch("/api/auth/status", { credentials: "same-origin", cache: "no-store" })
            .then(function (r) {
                return r.json();
            })
            .then(function (data) {
                if (data && data.logged_in && data.username) {
                    setAdminSessionStorage(data.username);
                } else if (data && Object.prototype.hasOwnProperty.call(data, "logged_in")) {
                    clearAdminSessionStorage();
                }
                return data || { logged_in: false };
            })
            .catch(function () {
                return { _networkError: true };
            });
    }

    global.setAdminSessionStorage = setAdminSessionStorage;
    global.clearAdminSessionStorage = clearAdminSessionStorage;
    global.syncAdminSessionFromFetch = syncAdminSessionFromFetch;
})(typeof window !== "undefined" ? window : this);

// Sibyl public demo: on /login?demo=1 show the demo login, with a button that fills it in.
(function () {
	if (!/^\/login\/?$/.test(location.pathname)) return;
	if (!/[?&]demo=1\b/.test(location.search) && !/#demo\b/.test(location.hash)) return;

	function ready(fn) {
		if (document.readyState !== "loading") fn();
		else document.addEventListener("DOMContentLoaded", fn);
	}

	ready(function () {
		fetch("/api/method/sibyl_app.demo.public_info", { headers: { Accept: "application/json" } })
			.then(function (r) { return r.json(); })
			.then(function (r) {
				var info = r && r.message;
				if (!info || !info.enabled) return;
				var form = document.querySelector(".form-signin") || document.querySelector("form.form-login") || document.querySelector("form");
				if (!form) return;
				var esc = function (s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; };
				var box = document.createElement("div");
				box.setAttribute("style",
					"margin:0 0 18px 0;padding:16px 18px;border:1px solid #d0d5dd;border-left:4px solid #14213d;border-radius:6px;" +
					"background:#f8fafc;font-size:13px;line-height:1.55;color:#1d2433;text-align:left;");
				box.innerHTML =
					'<div style="font-weight:700;font-size:14px;color:#14213d;margin-bottom:6px;">Try the live demo</div>' +
					'<div>Email: <b style="user-select:all">' + esc(info.user) + '</b></div>' +
					'<div>Password: <b style="user-select:all">' + esc(info.password) + '</b></div>' +
					'<button type="button" class="btn btn-sm btn-primary" style="margin-top:10px;width:100%">Fill in the demo login</button>' +
					'<div style="margin-top:10px;color:#667085;font-size:12px;">You will see ' + info.companies.length +
					' demo companies (' + info.companies.map(function (c) { return esc(c.industry); }).join(", ") +
					'). Switch company from any list or report. Demo emails are never sent.</div>';
				form.parentNode.insertBefore(box, form);
				box.querySelector("button").addEventListener("click", function () {
					var email = document.querySelector("#login_email") || form.querySelector("input[type=email],input[name=usr]");
					var pwd = document.querySelector("#login_password") || form.querySelector("input[type=password]");
					if (email) { email.value = info.user; email.dispatchEvent(new Event("input", { bubbles: true })); }
					if (pwd) { pwd.value = info.password; pwd.dispatchEvent(new Event("input", { bubbles: true })); }
					var submit = form.querySelector("button[type=submit], .btn-login");
					if (submit) submit.focus();
				});
			})
			.catch(function () {});
	});
})();

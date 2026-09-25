# Amiri Insurance Admin System

The blog admin now runs on **Python Flask**. PHP is no longer used.

## Run the site

```bash
py -3 -m pip install -r requirements.txt
py -3 app.py
```

Then open http://localhost:5000

On a VPS use gunicorn, not cPanel. See `DEPLOY.md`.

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

HTML lives in `templates/`. CSS, JS, and images live in `static/`.

## Default login

- **Username:** `admin`
- **Password:** `admin@amiri123`

Change these in `.env` before going live (`ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`).

## Pages

| Page | URL | Notes |
| --- | --- | --- |
| Login | `/admin-login.html` | Public |
| Dashboard | `/admin-blog.html` | Requires login |
| New post | `/post-blog.html` | Requires login |
| Logout | `/logout` | Clears the Flask session |

## API

- `GET /api/posts` — published posts
- `POST /api/posts` — create a post (logged-in)
- `GET /api/admin/posts` — all posts (logged-in)
- `PUT /api/admin/posts` — save the full post list (logged-in)
- `POST /api/auth/login`
- `GET /api/auth/status`
- `GET /logout` or `/api/auth/logout`

Posts are stored in `data/blog-posts.json`. Images go to `uploads/blog/`.

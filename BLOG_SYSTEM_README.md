# Amiri Insurance Blog System

Blog posts are managed through the Flask app (`app.py`). See `ADMIN_README.md` for login, APIs, and how to run the server.

## Public pages

- `blog.html` — published posts
- `blog-post.html` — single post
- `post-blog.html` — create a post (requires admin login)
- `admin-blog.html` — review, edit, publish, delete

## Storage

- `data/blog-posts.json`
- `static/uploads/blog/` for featured images
- HTML in `templates/`, assets in `static/`

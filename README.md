# Room Booking Platform

A room reservation system for organisations that rent out or schedule space.
Visitors book through a multi-step form and receive a booking number they can use
to retrieve, modify or cancel. Staff manage rooms, per-room equipment, bookings
and users from an admin dashboard.

Flask · MySQL · Flask-Login · Flask-Bcrypt · FullCalendar.

## Try it in about two minutes

```bash
git clone <this-repo> && cd room-booking-platform
cp .env.example .env
docker compose up -d --build
```

Open **http://localhost:8000**. Schema and demo data load automatically on first
start — four rooms, ten equipment items and five bookings, all fictional.

Sign in at **/login**:

| Account | Password | Role |
|---|---|---|
| `admin@example.com` | `admin123` | admin — dashboard, rooms, equipment, users |
| `user@example.com` | `user123` | user |

No mail server, no cloud account, no manual database setup. Notification emails
are logged rather than sent unless you enable mail.

Ports in use? Everything is overridable:

```bash
WEB_PORT=18100 DB_PORT_HOST=13316 docker compose up -d
```

## What it does

**Booking** — a multi-step form: personal details → event details → date and time
range → room selection → equipment and extras. Room availability is checked
against existing bookings before a reservation is accepted, so the same room
can't be double-booked for an overlapping window.

**Per-room equipment** — each room carries its own inventory (projector,
flipcharts, microphones…) with a maximum quantity a booking may request. The form
loads the right list when a room is picked.

**Self-service** — the booking number retrieves a reservation for modification or
cancellation. Cancelling requires a code emailed to the booking's address, so a
booking number alone isn't enough to cancel someone's reservation.

**Calendar** — all bookings on a FullCalendar month/week view.

**Admin** — booking and room counts, full booking list, room management (name,
capacity, cleaning charge), equipment management, and user management (add,
promote, deactivate, delete).

## Layout

```
app.py               all routes and logic (~1200 lines, single module)
templates/           21 Jinja templates, including the HTML emails
static/              CSS, JS, vendored FullCalendar
db/01-schema.sql     schema, applied automatically on first start
db/02-seed.sql       fictional demo data
```

Four tables: `users`, `resources` (rooms), `inventory` (per-room equipment),
`bookings`.

## Configuration

All via environment variables — see [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev placeholder | **The app refuses to start in production on the default** |
| `BRAND_NAME` / `BRAND_LOGO` | `Room Booking` / `images/logo.png` | `BRAND_LOGO` is a path under `static/`; empty renders the name as text |
| `DB_*` | wired to the compose MySQL | Point elsewhere for an external database |
| `MAIL_ENABLED` | `false` | When off, emails are logged instead of sent |
| `WEB_PORT` / `DB_PORT_HOST` | `8000` / `3316` | Host bindings |

## Notes on this release

This ran in production before being published. Preparing it surfaced problems
worth naming rather than quietly fixing:

**Three live credentials were hardcoded in `app.py`** — the Flask `SECRET_KEY`, a
real SMTP password, and the database password. The SMTP password appeared
**twice**: once in config, and again inside a separate raw `smtplib` function
that bypassed the configured mail setup entirely. All now come from the
environment, through a single mail path. Any deployment of the earlier code
should treat those credentials as compromised.

**Three routes had no authentication.** `/cancel_booking/<id>` accepted an
anonymous POST and deleted any booking by id; `/add_resource` let anyone create a
room; `/cancel_user_booking` read `current_user.email` without requiring a login,
so it raised on anonymous requests instead of denying cleanly. All three are now
behind `@login_required`, with the two admin actions behind a role check.

**There was no schema file.** The production database was built by hand on the
server, so `db/01-schema.sql` is reconstructed from every query in the
application. It adds constraints the original lacked: unique email on `users`,
unique `booking_number` (the generator picks a random six-digit number with no
collision check, so the database has to be the backstop), a foreign key from
`inventory` to `resources`, and an index on the columns the availability check
filters on.

**`requirements.txt` listed packages the app never imports** — a full
matplotlib/scipy/numpy/pillow tree — and pinned `mysql-connector`, the deprecated
package, rather than Oracle's maintained `mysql-connector-python`. It is now the
eight packages actually imported.

## Known limitations

Honest list, not a roadmap:

- **No tests.** None existed and none have been added yet.
- **No CSRF protection.** Forms post without tokens. ⚠️ Note that
  `templates/landing_page.html` currently states *"CSRF protection implemented on
  all forms"* — that claim is **not true** and should be removed or made true.
- **`bookings.resource` stores the room name as text**, not a foreign key.
  Renaming a room orphans its bookings.
- **The availability check has a gap.** It requires date ranges *and* time ranges
  to overlap as separate conditions, which misses a booking that spans midnight
  or runs across multiple days.
- **All logic lives in one ~1200-line module.** Fine at this size, awkward past it.
- FullCalendar is both vendored in `static/` *and* proxied from a CDN at request
  time by `/get_fullcalendar_css` and `/get_fullcalendar_js` — one should go.

## Licence

MIT — see [LICENSE](LICENSE).

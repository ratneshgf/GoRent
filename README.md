# GoRent direct car rentals

**Live frontend:** [gorent-frontend.vercel.app](https://gorent-frontend.vercel.app/)

For a split Render backend and Vercel frontend deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).

Django and Django REST Framework app with owner and renter accounts. Owners complete a local ID file check before listing cars; renters upload an ID with each rental request; owners review that private ID and accept or reject requests. Acceptance requires a pickup address, and the renter receives a Google Maps driving route.

## Local preview

```powershell
pip install -r requirements.txt
python manage.py migrate
$env:DEBUG="1"              # local HTTP preview, even if .env has DEBUG=0
python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000. Register an owner to list cars; Explore shows only cars listed by owners through the app. Demo seeding is disabled. The project reads `.env` automatically; do not commit it. Use HTTPS, a real secret key, and a production server before public deployment.

## Fresh Supabase PostgreSQL database

GoRent can use a separate Supabase project. The existing SQLite file and any other Supabase project are not migrated or changed by these steps. Start with an empty GoRent database; create new owner and renter accounts after migration.

1. In the Supabase dashboard, choose your organization, click **New project**, name it **GoRent**, set a strong database password and select a nearby region. Wait until the project is ready. Do not select the project used by your other app.
2. Open the **new GoRent project** and click **Connect**. Copy its **Session pooler** PostgreSQL URI (port `5432`). Use the database password you created for this new project in place of the URI's password placeholder. If it contains URL special characters such as `@`, `#`, `/` or `:`, percent-encode the password portion of the URI.
3. In this project's ignored `.env` file, set `SUPABASE_PROJECT_REF` to the part after `postgres.` in the Session pooler username, and set `DATABASE_URL` to that complete URI with `?sslmode=require` (or append `&sslmode=require` if it already has a query). Keep the URI and password out of chat and Git. Do not use the Supabase anon or service-role API keys here.
4. Confirm the project reference and pooler host in `.env` belong to **GoRent**. The app checks the URI's project reference against `SUPABASE_PROJECT_REF` before it can connect. Then run:

   ```powershell
   python manage.py check
   python manage.py migrate
   python manage.py runserver 127.0.0.1:8000
   ```

5. Register fresh owner and renter accounts in the app. `DATABASE_URL` takes priority over the old `POSTGRES_DB` settings; without either, local SQLite remains the default. Cloudinary photos and private uploaded ID files have separate storage settings.

If migration reports a connection error, verify the new project's Session pooler URI, password, and reference in `.env`. A password change in Supabase must also be reflected in the URI.

## How it works

1. Register as a car owner. In the full-width Dashboard, use **Add a car** to save car details as a private draft in **My cars**, or list immediately after the owner ID check. Drafts are visible only to their owner and can be edited before listing. From **My cars**, click **List car** whenever you want the saved car to appear in renter Explore. The local ID file check is required to publish, but not to save a draft.
2. Register as a renter, find a car, choose **Days** or **Hours** on its booking page, choose an ID type, upload an ID and consent to privately share it with the owner, then click **Request this car**. Hourly rentals start at one hour; the hourly rate is the daily price divided by 24 and rounded up to the next rupee, and partial hours are billed as full hours. The owner must open the document before accepting; replacing an ID requires the owner to open the new file again. Older requests without an ID offer an Upload ID action in My trips. Owner and renter can exchange messages.
3. The owner clicks **Accept & set pickup**, enters a precise address or shares the device location, and accepts. The renter sees the pickup address and **Open Google Maps route** in My trips. Google Maps opens driving directions from the renter's current location. No Google Maps API key is needed for this link.
4. The owner may reject a request. A renter may cancel a pending request at any time; either party may cancel a confirmed booking **before pickup starts** by giving a reason. The app does not charge a cancellation fee or issue an automatic refund. Active rentals cannot be cancelled through this flow; the owner can mark a dispute instead.
5. As soon as the owner accepts, the car is hidden from renter Explore and cannot receive new requests. It stays hidden after completion or cancellation until the owner clicks **Relist car**. Relisting is blocked while a rental is confirmed, active, returned, or disputed.
6. Cash is handled directly at handover. Starting a rental does **not** mark it paid. After handover, the renter clicks **I paid cash** and the owner clicks **Confirm cash received**. Both actions are required before the owner can mark the car returned. Both parties can then open a printable cash receipt. The receipt records their confirmations; it is not a bank or payment gateway proof, and it excludes any deposit. Older bookings previously auto-marked paid are now shown as unverified until both parties confirm them.

Requests appear when the dashboard loads and auto-refresh while open. Browser geolocation works on localhost or HTTPS and needs location permission. Owners can enter an address manually if permission is unavailable.

## Owner and renter navigation

- Owners land on a dedicated home page with owner headlines rotating every three seconds, a **Rent out your next car** action bar, listing and request counts, active rentals, and tracked booking value. They do not see the renter car catalog or renter search bar.
- Owner **Explore** shows their own cars, including hidden rentals, with status and rental counts. Owners can relist an available car after its rental ends. **Search** filters their cars by name, city and rental status. Owners can edit listing details and photos there.
- Owner **History** uses booking records for cars already handed over, including active, returned and completed rentals. The full-width dashboard has a left sidebar for Overview, Requests, My cars, Add a car and ID check. Each section opens separately; My cars includes saved drafts, photo, edit, list and relist controls.
- Renters and guests keep the car catalog, three-second renter headlines, car search and browser search history.


## Local ID check and production verification

The local `.env` has `OWNER_ID_MODE=local_demo`; run the preview with `DEBUG=1`. This checks the uploaded file type and size and stores it in private server storage. It does **not** prove that a government, employer or school issued the ID or that the uploader owns it. The UI calls this a local check, never government verification. A local demo check cannot unlock new listings with `DEBUG=0`. Connect an authorized DigiLocker/KYC provider before public launch to offer real authenticity verification. The document is never in Cloudinary or public listings. Aadhaar uploads require the owner or renter to confirm that the first eight digits are masked. The app has no separate Aadhaar-number field and does not automatically detect whether an uploaded copy is masked.

A renter's ID is served only through an authenticated owner endpoint; it is unavailable to guests, other renters and other owners. The owner must open it before accepting, and access closes after rejection or cancellation. Documents already stored for older requests remain private.

## Cloudinary photos

Set `CLOUDINARY_URL=cloudinary://API_KEY:API_SECRET@CLOUD_NAME` in ignored `.env`. Owners can upload JPG, PNG or WebP photos up to 10 MB while listing or later in **Your cars**. The API secret stays on the server. Listings can also be created without a photo.

## API

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET/PATCH /api/users/me`, `POST /api/owner/identity` |
| Cars | `GET /api/vehicles`, `GET /api/vehicles/{id}`, `GET /api/vehicles/mine`, `POST /api/vehicles` (set `save_as_draft=true` to save privately), `POST /api/vehicles/{id}/publish` to list a draft, `POST /api/vehicles/{id}/relist` after a rental, `PATCH /api/vehicles/{id}` |
| Requests | `POST /api/bookings` with `vehicle`, `booking_type=daily`, `start`, `end`, `id_type`, `id_document`, `consent`; for hourly requests use `booking_type=hourly`, `start_at`, `end_at` instead of dates. Also `GET /api/bookings`, `POST /api/bookings/{id}/identity`, `GET /api/bookings/{id}/document`, `POST /api/bookings/{id}/transition` (`reason` required for confirmed cancellation), `POST /api/bookings/{id}/payment` (`action=mark_paid` or `confirm_received`), and `GET /api/bookings/{id}/receipt`. |
| Pickup | To accept, post `status=confirmed`, `pickup_address`, and optionally both `pickup_lat` and `pickup_lng` to the transition endpoint. |
| Messages and reviews | `GET/POST /api/bookings/{id}/messages`, `POST /api/reviews` for completed rentals |

Token authentication uses `Authorization: Token <key>`. Listing and booking data is persisted in the configured database. Set `DATABASE_URL` and `SUPABASE_PROJECT_REF` for the isolated Supabase project; `POSTGRES_DB` and related environment variables remain available for other PostgreSQL setups. SQLite is the local default.

Automated notifications, online payments, and deployment are still future work.

# Deploying to Google Cloud Run

The cloud setup runs one Cloud Run service with its own Sign in with Google (an allow-list of accounts),
with PostgreSQL on Cloud SQL (IAM sign-in, so no database password exists), attachments in a private Cloud
Storage bucket, and the Anthropic API key and a read-only GitHub token in Secret Manager.

Replace the placeholders: `PROJECT`, `REGION` (e.g. `asia-south1`), `INSTANCE` (Cloud SQL instance), `BUCKET`,
`AR_REPO` (an Artifact Registry Docker repository in `REGION`), and the e-mail addresses.

## 1. One-time setup

```bash
# APIs
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  iap.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com --project=PROJECT

# Service account the app runs as
gcloud iam service-accounts create sdlc-orchestrator --display-name="SDLC Orchestrator" --project=PROJECT
SA=sdlc-orchestrator@PROJECT.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding PROJECT --member=serviceAccount:$SA --role=roles/cloudsql.client
gcloud projects add-iam-policy-binding PROJECT --member=serviceAccount:$SA --role=roles/cloudsql.instanceUser
```

### Database (Cloud SQL, IAM sign-in)

IAM database sign-in needs the instance flag `cloudsql.iam_authentication=on`. **Setting a flag can restart the
instance** - do it in a quiet window if other apps share it, and pass every flag the instance already has
(`--database-flags` replaces the whole list).

```bash
gcloud sql instances patch INSTANCE --database-flags=cloudsql.iam_authentication=on --project=PROJECT
gcloud sql users create sdlc-orchestrator@PROJECT.iam --instance=INSTANCE --type=cloud_iam_service_account --project=PROJECT
```

Create the database **with psql as your admin user**, not with `gcloud sql databases create`: a database created
through the API is owned by a Google-managed role, and your admin user then cannot grant rights on its `public`
schema (PostgreSQL 15+). Connect with `-h 127.0.0.1` (the Cloud SQL proxy may not listen on IPv6), first to
`postgres`:

```sql
CREATE DATABASE sdlc_pm;
GRANT CONNECT, TEMPORARY ON DATABASE sdlc_pm TO "sdlc-orchestrator@PROJECT.iam";
```

then reconnect to `sdlc_pm` itself (`-d sdlc_pm`) and run:

```sql
GRANT ALL ON SCHEMA public TO "sdlc-orchestrator@PROJECT.iam";
SELECT has_schema_privilege('sdlc-orchestrator@PROJECT.iam', 'public', 'CREATE');  -- must be t
```

A `WARNING: no privileges were granted` means you are in the wrong database or not its owner.

The app creates its tables itself (`alembic upgrade head` runs at container start).

### Attachments bucket

```bash
gcloud storage buckets create gs://BUCKET --location=REGION --uniform-bucket-level-access \
  --public-access-prevention --project=PROJECT
gcloud storage buckets add-iam-policy-binding gs://BUCKET --member=serviceAccount:$SA --role=roles/storage.objectAdmin
```

### Secrets

Create them yourself so the values never pass through anyone else. `--data-file=-` reads from the terminal:
paste the value, press Enter, then Ctrl+Z and Enter (Windows) or Ctrl+D (macOS/Linux).

```bash
gcloud secrets create sdlc-anthropic-api-key --data-file=- --project=PROJECT
gcloud secrets create sdlc-github-token --data-file=- --project=PROJECT
gcloud secrets add-iam-policy-binding sdlc-anthropic-api-key --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project=PROJECT
gcloud secrets add-iam-policy-binding sdlc-github-token --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project=PROJECT
```

The GitHub token should be a fine-grained token limited to the project repositories, with **Contents:
read-only** and nothing else. If no project uses a private repository, store any placeholder text.

### Let Cloud Build deploy as the service account

```bash
gcloud iam service-accounts add-iam-policy-binding $SA --member=serviceAccount:CLOUD_BUILD_SA --role=roles/iam.serviceAccountUser
```

`CLOUD_BUILD_SA` is the account your builds run as (often `PROJECT_NUMBER-compute@developer.gserviceaccount.com`).
It also needs `roles/run.admin`.

## 2. Build and deploy

```bash
gcloud builds submit --config cloudbuild.yaml --project=PROJECT \
  --substitutions=_SQL_INSTANCE=PROJECT:REGION:INSTANCE,_BUCKET=BUCKET,_AR_REPO=AR_REPO
```

## 3. Who can sign in

The app has its own **Sign in with Google** with an allow-list. (Cloud Run's built-in IAP only admits accounts
that belong to the project's organisation, so it refuses personal Gmail accounts.)

1. **OAuth client.** Cloud Console -> Google Auth Platform: set up Branding (app name, support e-mail), Audience
   *External* (in *Testing*, add each user as a test user), then **Clients -> Create client -> Web application**
   with the authorised redirect URI `https://SERVICE_URL/auth/callback`. Note the client ID; keep the secret.
2. **Secrets.** Store the client secret as `sdlc-google-client-secret`, and a random string of at least 32
   characters as `sdlc-session-secret` (it signs the session cookie). Grant the service account
   `roles/secretmanager.secretAccessor` on both.
3. **Deploy** with `_GOOGLE_CLIENT_ID`, `_PUBLIC_URL=https://SERVICE_URL` and `_ALLOWED_EMAILS` (separate
   addresses with `;`) added to `--substitutions`.
4. **Let browsers reach the service** (every page still requires sign-in; only `/healthz` and `/auth/*` are open):

```bash
gcloud run services add-iam-policy-binding sdlc-orchestrator --region=REGION --project=PROJECT   --member=allUsers --role=roles/run.invoker
```

To add or remove people later, redeploy with a new `_ALLOWED_EMAILS`. The sidebar shows the signed-in e-mail
with a Sign out link; it is also the default approver and reporter name.

## Differences from running locally

| | Local | Cloud |
|---|---|---|
| Database | SQLite file (or `DATABASE_URL`) | Cloud SQL, IAM sign-in; no silent SQLite fallback |
| Attachments | `data/attachments/` | Cloud Storage bucket |
| Code reading (stages 3, 6, 7) | A folder path on the project | An `https://github.com/owner/repo` URL on the project; a read-only clone is refreshed at most every 5 minutes |
| Repo Sync | Writes `.sdlc/` into the folder | Not available for URL repositories - use Download all |
| Sign-in | None | Sign in with Google, accounts on `ALLOWED_EMAILS` |

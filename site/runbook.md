# Firebase Hosting Runbook

This runbook deploys this directory to Firebase Hosting in Google Cloud project `pt-1-493616`, then maps it to `skills.ritualfoundation.org`.

## Architecture

- Source: `index.html` and `scanner-preview.png` in this directory
- Hosting: Firebase Hosting
- Project: `pt-1-493616`
- Current Hosting site ID: `pt-1-493616`
- Firebase deploy target alias: `skills`
- Production domain: `skills.ritualfoundation.org`
- DNS provider: Namecheap, unless the domain uses custom nameservers

Firebase Hosting is the simplest path for this site because it handles static hosting, CDN delivery, and managed SSL certificates without a Cloud Run container, static IP, or load balancer.

The clearer Hosting site ID `ritual-dapp-skills` was validated as available, but creating an additional Firebase Hosting site currently returns `PERMISSION_DENIED` from the Hosting API. Until that is resolved in Firebase Console or through a Firebase CLI login with sufficient access, the `skills` deploy target points at the default Hosting site `pt-1-493616`.

## Fixing the Firebase Hosting Site Name

The Firebase project ID `pt-1-493616` cannot be renamed. To get a better Firebase-provided URL, create an additional Firebase Hosting site with a clearer site ID, then move the `skills.ritualfoundation.org` custom domain to that site.

The desired site ID is:

```text
ritual-dapp-skills
```

That would create this Firebase-provided URL:

```text
https://ritual-dapp-skills.web.app
```

If `hosting:sites:create` fails with `Failed to authenticate` or `invalid_rapt`, reauthenticate the Firebase CLI:

```sh
npx -y firebase-tools@15.15.0 login --reauth
```

Then create the named Hosting site:

```sh
npx -y firebase-tools@15.15.0 hosting:sites:create ritual-dapp-skills --project pt-1-493616
```

Only continue if the create command succeeds. If it returns `403 PERMISSION_DENIED`, do not run `target:apply` yet.

If `target:apply` was run after a failed site creation, repair the target mapping:

```sh
npx -y firebase-tools@15.15.0 target:clear hosting skills --project pt-1-493616
npx -y firebase-tools@15.15.0 target:apply hosting skills pt-1-493616 --project pt-1-493616
```

Point the local `skills` deploy target at the new site:

```sh
npx -y firebase-tools@15.15.0 target:apply hosting skills ritual-dapp-skills --project pt-1-493616
```

Deploy this directory to the new site:

```sh
npx -y firebase-tools@15.15.0 deploy --only hosting:skills --project pt-1-493616
```

Move the custom domain from the old default site to the new site. In Firebase Console, remove `skills.ritualfoundation.org` from the `pt-1-493616` Hosting site, then add it to the `ritual-dapp-skills` Hosting site.

After the domain is added to the new site, fetch the current DNS requirements:

```sh
TOKEN="$(gcloud auth print-access-token)"
curl -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Goog-User-Project: pt-1-493616" \
  "https://firebasehosting.googleapis.com/v1beta1/projects/pt-1-493616/sites/ritual-dapp-skills/customDomains/skills.ritualfoundation.org" \
  | jq '{hostState, ownershipState, cert: {type: .cert.type, state: .cert.state}, requiredDnsUpdates, certDns: .cert.verification.dns.desired}'
```

Do not update Namecheap until this command shows the DNS records for the new `ritual-dapp-skills` site. The CNAME target should become `ritual-dapp-skills.web.app`.

## Repo Configuration

This directory includes:

- `.firebaserc`: sets the default Firebase project to `pt-1-493616` and maps the `skills` deploy target to the current Hosting site
- `firebase.json`: deploys this directory to Firebase Hosting and excludes Firebase metadata, this runbook, and `Dockerfile`
- `runbook.md`: this runbook

The `Dockerfile` is kept for Cloud Run/container use, but Firebase Hosting does not use it.

Commit `.firebaserc`. It contains project aliases and target mappings only; it does not contain Firebase auth tokens or secrets.

## Prerequisites

1. Confirm the active Google Cloud project:

   ```sh
   gcloud config get-value project
   ```

   Expected output:

   ```text
   pt-1-493616
   ```

2. Confirm the active Google account has access to the project:

   ```sh
   gcloud auth list --filter=status:ACTIVE --format='value(account)'
   ```

3. Authenticate the Firebase CLI. `gcloud` auth is not always enough for `firebase-tools`.

   ```sh
   npx -y firebase-tools@15.15.0 login
   ```

4. Confirm Firebase CLI access:

   ```sh
   npx -y firebase-tools@15.15.0 projects:list
   ```

## One-Time Firebase Setup

For `pt-1-493616`, this setup has already been completed. Keep these steps for rebuilding the setup in a new environment or recovering from accidental deletion.

Enable the Firebase APIs:

```sh
gcloud services enable firebase.googleapis.com firebasehosting.googleapis.com --project pt-1-493616
```

If `pt-1-493616` is not listed as a Firebase project, add Firebase resources to the existing Google Cloud project:

```sh
npx -y firebase-tools@15.15.0 projects:addfirebase pt-1-493616
```

Check for the default Hosting site:

```sh
npx -y firebase-tools@15.15.0 hosting:sites:list --project pt-1-493616
```

The expected default Hosting site ID is `pt-1-493616`.

If the default site does not exist, create it:

```sh
npx -y firebase-tools@15.15.0 hosting:sites:create pt-1-493616 --project pt-1-493616
```

To retry creating the clearer site ID:

```sh
npx -y firebase-tools@15.15.0 hosting:sites:create ritual-dapp-skills --project pt-1-493616
```

If that succeeds, update `site/.firebaserc` so the `skills` target maps to `ritual-dapp-skills`, then redeploy and recreate the `skills.ritualfoundation.org` custom-domain resource on the new Hosting site before updating Namecheap DNS.

## Deploy

From this directory:

```sh
npx -y firebase-tools@15.15.0 deploy --only hosting:skills --project pt-1-493616
```

The deploy output includes the Firebase Hosting URL. Open it and confirm the page renders before changing DNS.

## Map `skills.ritualfoundation.org`

For `pt-1-493616`, the Firebase custom-domain resource has already been created. DNS still has to be configured wherever `ritualfoundation.org` DNS is hosted.

Check the current Firebase domain status and required DNS records:

```sh
TOKEN="$(gcloud auth print-access-token)"
curl -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Goog-User-Project: pt-1-493616" \
  "https://firebasehosting.googleapis.com/v1beta1/projects/pt-1-493616/sites/pt-1-493616/customDomains/skills.ritualfoundation.org" \
  | jq '{hostState, ownershipState, cert: {type: .cert.type, state: .cert.state}, requiredDnsUpdates, certDns: .cert.verification.dns.desired}'
```

If the custom-domain resource does not exist, create it:

```sh
TOKEN="$(gcloud auth print-access-token)"
curl -sS \
  -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Goog-User-Project: pt-1-493616" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "https://firebasehosting.googleapis.com/v1beta1/projects/pt-1-493616/sites/pt-1-493616/customDomains?customDomainId=skills.ritualfoundation.org"
```

You can also use the Firebase console:

1. Open the Firebase console.
2. Select project `pt-1-493616`.
3. Go to Hosting.
4. Click Add custom domain.
5. Enter:

   ```text
   skills.ritualfoundation.org
   ```

6. Use Quick Setup unless the subdomain is already serving production traffic somewhere else.
7. Firebase will show DNS records for verification and routing.
8. In Namecheap, open `ritualfoundation.org` DNS settings.
9. Add the records exactly as Firebase shows them.

For Namecheap, the host/name for this subdomain is usually:

```text
skills
```

For ACME certificate TXT records under `_acme-challenge.skills.ritualfoundation.org`, the Namecheap host/name is usually:

```text
_acme-challenge.skills
```

Use the exact record types and values from Firebase. Remove any existing `A`, `AAAA`, or `CNAME` records for `skills` that point to another provider. If Firebase asks for a CNAME, do not also add an `A` record for the same host.

If `ritualfoundation.org` uses custom nameservers, update DNS at that DNS provider instead of Namecheap.

## SSL and DNS Verification

Firebase provisions and renews SSL certificates automatically. Certificate provisioning can take up to 24 hours, but usually finishes sooner.

Check DNS:

```sh
dig +short skills.ritualfoundation.org A
dig +short skills.ritualfoundation.org AAAA
```

Check HTTP response after DNS and SSL are ready:

```sh
curl -I https://skills.ritualfoundation.org
```

Expected result:

```text
HTTP/2 200
```

## Updating the Site

1. Edit `index.html` or assets in this directory.
2. Deploy again:

   ```sh
   cd site
   npx -y firebase-tools@15.15.0 deploy --only hosting:skills --project pt-1-493616
   ```

3. Verify the Firebase Hosting URL and `https://skills.ritualfoundation.org`.

## Rollback

Use Firebase Console:

1. Open project `pt-1-493616`.
2. Go to Hosting.
3. Open Release history.
4. Select the previous known-good release.
5. Click Roll back.

## References

- Firebase Hosting custom domains: https://firebase.google.com/docs/hosting/custom-domain
- Firebase CLI reference: https://firebase.google.com/docs/cli
- Firebase Hosting REST deploy flow: https://firebase.google.com/docs/hosting/api-deploy
- Firebase custom domain REST API: https://firebase.google.com/docs/reference/hosting/rest/v1beta1/projects.sites.customDomains

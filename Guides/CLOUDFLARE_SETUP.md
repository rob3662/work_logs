# Cloudflare (generic)

- SSL/TLS: use **Full (strict)** when terminating TLS at Cloudflare with a valid origin cert or tunnel.

Replace any old domain names in your own notes with `DOMAIN_NAME` from `.env`.

## Dedicated tunnel and a subdomain on an existing apex (e.g. `logs.brakesystems.ca`)

Each `cloudflared` tunnel has its own tunnel UUID. Public hostnames must resolve to **that** tunnel’s `*.cfargotunnel.com` target—not to another tunnel that already serves `www` or other apps on the same apex.

1. **DNS (required)**  
   In the Cloudflare DNS zone for the **apex** of your public hostname (for `logs.brakesystems.ca`, open the **brakesystems.ca** zone—not another zone on the account), add:

   - **Type:** CNAME (or the **Tunnel** record type in the dashboard, selecting this site’s tunnel name).  
   - **Name:** the subdomain part only (for `logs.brakesystems.ca`, use **`logs`**).  
   - **Target / tunnel:** `<CLOUDFLARE_TUNNEL_ID>.cfargotunnel.com` (UUID from `.env`, proxied / orange cloud).

   Until this record exists in the **correct** zone, the hostname will not reach your origin even if Zero Trust shows a route and the tunnel is **Healthy**.

2. **Do not merge into the wrong tunnel**  
   You do not add `logs` to the **brakesystems** tunnel’s ingress unless you intentionally want one `cloudflared` process to serve every hostname. This project uses a **separate** tunnel (`<WEBSITE_NAME>-tunnel`); DNS for `logs` must point at **that** tunnel’s UUID.

3. **`cloudflared tunnel route dns` (optional)**  
   This CLI can create a CNAME automatically, but on accounts with **multiple** zones it may write the record into the wrong zone. For **brakesystems.ca** (and similar), adding the record **manually** in the correct DNS zone is usually simpler and clearer.

4. **SSL**  
   After DNS propagates, keep SSL/TLS mode **Full (strict)** (or **Full**) as appropriate for your origin.

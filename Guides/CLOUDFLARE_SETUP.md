# Cloudflare (generic)

- Point DNS for your domain to the tunnel or origin as you prefer.
- SSL/TLS: use **Full (strict)** when terminating TLS at Cloudflare with a valid origin cert or tunnel.
- Create a CNAME for the app hostname to your tunnel target when using Cloudflared.

Replace any old domain names in your own notes with `DOMAIN_NAME` from `.env`.

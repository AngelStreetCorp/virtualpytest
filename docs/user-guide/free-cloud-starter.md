# Free cloud starter

This is the lowest-cost way to demonstrate VirtualPyTest in the cloud. It is a
showcase and test environment, not a production deployment: free services sleep,
have small resource limits, and may lose local or in-memory state.

## Recommended architecture

```text
Render free web services
  frontend + backend server
          │
          ├── Supabase Free: Postgres, Auth, REST, Storage
          ├── Render Key Value: Redis-compatible cache
          └── Linux VM: VirtualPyTest host and virtual devices
```

The host is a Linux VM rather than a Render Free service. A host needs to run
continuously, receive host traffic, and may need access to emulators, USB, ADB,
Bluetooth, IR, or capture devices. Render Free services sleep after inactivity and
do not support the private-service shape needed for a continuously reachable host.
For a cloud-only demo with virtual devices, a small VM can run the host instead.

## Services and free-tier choices

| Part | Starter choice | Notes |
|---|---|---|
| Frontend | Render Free Web Service or Static Site | Sleeps when idle; first request can be slow. |
| Backend server | Render Free Web Service | Use hosted Supabase and external storage. |
| Database/Auth | [Supabase Free](https://supabase.com) | Create a project and apply our schema. |
| Redis | Render Free Key Value | Redis-compatible, but in-memory and disposable on restart. |
| Object storage | Supabase Storage or an S3-compatible provider | Do not use local container storage on a free web service. |
| Host | A Linux VM | Provider is interchangeable; see the host options below. |
| Grafana | Optional | Omit for the smallest demo or run it on the VM. |

Render currently offers Free plans for web services, static sites, Postgres, and
Key Value. Free Postgres expires after 30 days, so this guide uses Supabase instead.
See Render's [free-tier limitations](https://render.com/docs/free) before presenting
this as a persistent service.

## 1. Create Supabase

Follow [Using a cloud Supabase project](../get-started/supabase.md#using-a-cloud-supabase-project).
Record the project URL, public/anon key, server-side service key, JWT secret, and
database connection string. Apply the schema once:

```bash
./setup/db/apply_schema.sh \
  "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
```

Keep the service key and database password only in the Render server and host
environment. Never put them in frontend variables.

## 2. Deploy the frontend and server

Use the existing [managed cloud guide](../get-started/cloud-setup.md) for Render
configuration. Set the server's Supabase variables in Render, then point the
frontend at the Render server URL. Use the published GHCR image tag when creating
an image-backed service, or connect Render to the repository and build the Dockerfile.

## 3. Choose a Linux VM for the host

The host can be placed on any reachable Linux VM. The provider is deliberately not
part of the application contract.

### AWS

AWS EC2's current T4g free trial provides an ARM Linux VM for eligible accounts.
It is time-limited, requires billing setup, and needs ARM64 images. See the
[AWS free-tier documentation](https://aws.amazon.com/ec2/faqs/). Set a billing
alarm before starting it.

### Google Cloud

Google's Always Free `e2-micro` is easy to obtain in selected US regions, but its
1 GiB RAM and fractional CPU are generally too small for the complete host stack.
Use it only for a minimal or intermittent virtual-device demo. See the
[Google Cloud Free Tier](https://cloud.google.com/free/docs/free-cloud-features).

### Oracle Cloud

Oracle Cloud Always Free offers the most capacity, but availability and account
creation vary by region. Its Ampere VM is ARM64, so the same multi-architecture
image requirement applies. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

## 4. Connect the host

On the Linux VM, use [Add a host](../get-started/add-a-host.md). Configure the host
with the same cloud server URL, Supabase URL, public key, service key, and storage
settings used by the server. Protect the host API with a firewall or VPN; do not
expose its control and VNC ports openly to the internet.

## What this starter does not promise

- Render Free is not always-on and is not production hosting.
- A free VM may be reclaimed, suspended, or subject to regional capacity limits.
- Physical HDMI, USB, Bluetooth, IR, and capture hardware must remain attached to a
  machine that can access it.
- Grafana is optional in the free showcase. The full Compose installation remains
  the supported path for the complete self-hosted platform.

